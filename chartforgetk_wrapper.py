from ChartForgeTK import CandlestickChart
from ChartForgeTK import LineChart
from typing import List, Tuple
import tkinter as tk
from tkinter import ttk

class CandlestickChartNoLabels(CandlestickChart):
    def __init__(self, *args, show_labels=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_labels = show_labels
        self.grid(row=0, column=0, sticky="nsew")
        self.watchdog_id = None

    def plot(self, data: List[Tuple[float, float, float, float, float]], title: str = "Candlestick Chart", animation_flag: bool = False):
        """Plot an improved candlestick chart with (index, open, high, low, close) data"""
        if not data:
            raise ValueError("Data cannot be empty")
        if not all(isinstance(d, tuple) and len(d) == 5 and 
                  all(isinstance(v, (int, float)) for v in d) for d in data):
            raise TypeError("Data must be a list of (index, open, high, low, close) number tuples")
        
        # Store timestamps for axis labeling
        self.timestamps = getattr(self, "timestamps", None)   
        self.data = sorted(data, key=lambda x: x[0])  # Sort by index
        
        # Calculate ranges
        indices, opens, highs, lows, closes = zip(*self.data)
        self.x_min, self.x_max = min(indices), max(indices)
        self.y_min, self.y_max = min(lows), max(highs)
        x_padding = (self.x_max - self.x_min) * 0.1 or 1
        y_padding = (self.y_max - self.y_min) * 0.1 or 1
        self.x_min -= x_padding
        self.x_max += x_padding
        self.y_min -= y_padding
        self.y_max += y_padding
        
        self.title = title
        self.x_label = "Time/Index"
        self.y_label = "Price"
        
        self.canvas.delete('all')
        self.elements.clear()
        
        self._draw_axes(self.x_min, self.x_max, self.y_min, self.y_max)
        self._animate_candles(animate_last_only=animation_flag)
        self._add_interactive_effects()

    def _draw_axes(self, x_min: float, x_max: float, y_min: float, y_max: float):
        """Override: draw axes but replace numeric x-ticks with timestamp labels."""
        # Store ranges
        self.x_min, self.x_max = x_min, x_max
        self.y_min, self.y_max = y_min, y_max

        # Draw grid
        self._draw_grid(x_min, x_max, y_min, y_max)

        # Y-axis (left)
        self.canvas.create_line(
            self.padding, self.padding,
            self.padding, self.height - self.padding,
            fill=self.style.AXIS_COLOR,
            width=self.style.AXIS_WIDTH,
            capstyle=tk.ROUND
        )

        # X-axis (at y=0 or bottom)
        y_zero = 0 if y_min <= 0 <= y_max else y_min
        axis_y = self._data_to_pixel_y(y_zero, y_min, y_max)

        self.canvas.create_line(
            self.padding, axis_y,
            self.width - self.padding, axis_y,
            fill=self.style.AXIS_COLOR,
            width=self.style.AXIS_WIDTH,
            capstyle=tk.ROUND
        )

        # --- NEW: Timestamp-based X-axis labels ---
        if hasattr(self, "timestamps") and self.timestamps:
            num_labels = 5
            step = max(1, len(self.timestamps) // num_labels)

            for i in range(0, len(self.timestamps), step):
                ts = self.timestamps[i]
                label = ts.strftime("%Y-%m-%d %H:%M")

                x_pos = self._data_to_pixel_x(i, x_min, x_max)

                self.canvas.create_text(
                    x_pos,
                    axis_y + 10,
                    text=label,
                    font=("Arial", 10),
                    fill=self.style.TEXT_SECONDARY,
                    anchor="n"
                )

            # Skip numeric x-ticks
            skip_x_ticks = True
        else:
            skip_x_ticks = False

        # Draw ticks (with x-axis optionally skipped)
        self._draw_ticks(x_min, x_max, y_min, y_max, skip_x_ticks=skip_x_ticks)

        # Title
        if self.title:
            self.canvas.create_text(
                self.width / 2, self.padding / 2,
                text=self.title,
                font=self.style.TITLE_FONT,
                fill=self.style.TEXT,
                anchor='center'
            )

        # X label
        if self.x_label:
            self.canvas.create_text(
                self.width / 2, self.height - self.padding / 3,
                text=self.x_label,
                font=self.style.LABEL_FONT,
                fill=self.style.TEXT_SECONDARY,
                anchor='center'
            )

        # Y label
        if self.y_label:
            self.canvas.create_text(
                self.padding / 3, self.height / 2,
                text=self.y_label,
                font=self.style.LABEL_FONT,
                fill=self.style.TEXT_SECONDARY,
                anchor='center',
                angle=90
            )
    
    def _draw_ticks(self, x_min, x_max, y_min, y_max, skip_x_ticks=False):
        """Override: allow skipping numeric x-ticks when timestamp labels are used."""

        # --- Y-axis ticks (unchanged) ---
        # keep your existing Y tick logic here

        # --- X-axis ticks (conditionally skipped) ---
        if not skip_x_ticks:
            # keep your existing numeric x-tick logic here
            pass
        
    def _animate_candles(self, animate_last_only: bool = False):
        """Animate candles. If animate_last_only=True, only the last candle animates.
           Added ability through show_labels to turn on/off high/low labels.
        """
        def ease(t):
            return t * t * (3 - 2 * t)

        candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
        candle_width = candle_spacing * self.candle_width_factor

        def update_animation(frame: int, total_frames: int):
            if not self.canvas.winfo_exists():
                return  # widget destroyed, stop updating

            progress = ease(frame / total_frames)

            try:
                for item in self.elements:
                    self.canvas.delete(item)
                self.elements.clear()

                last_index = len(self.data) - 1

                for i, (index, open_price, high, low, close_price) in enumerate(self.data):
                    x = self._data_to_pixel_x(index, self.x_min, self.x_max)
                    y_open = self._data_to_pixel_y(open_price, self.y_min, self.y_max)
                    y_high = self._data_to_pixel_y(high, self.y_min, self.y_max)
                    y_low = self._data_to_pixel_y(low, self.y_min, self.y_max)
                    y_close = self._data_to_pixel_y(close_price, self.y_min, self.y_max)

                    fill_color = "#4CAF50" if close_price >= open_price else "#F44336"
                    outline_color = self.style.adjust_brightness(fill_color, 0.8)

                    # Decide whether this candle should animate
                    if animate_last_only and i != last_index:
                        candle_progress = 1.0
                    else:
                        candle_progress = progress

                    # Candle body
                    y_mid = (y_open + y_close) / 2
                    candle_height = abs(y_close - y_open) * candle_progress
                    if candle_height < 1:
                        candle_height = 1
                    y_top = y_mid - candle_height / 2
                    y_bottom = y_mid + candle_height / 2

                    # Wick
                    y_mid_wick = (y_high + y_low) / 2
                    half_wick_length = (y_low - y_high) / 2 * candle_progress
                    wick = self.canvas.create_line(
                        x, y_mid_wick - half_wick_length,
                        x, y_mid_wick + half_wick_length,
                        fill=self.style.TEXT_SECONDARY,
                        width=self.wick_width,
                        tags=('wick', f'candle_{i}')
                    )
                    self.elements.append(wick)

                    # Shadow
                    shadow = self.canvas.create_rectangle(
                        x - candle_width/2 + 2, y_top + 2,
                        x + candle_width/2 + 2, y_bottom + 2,
                        fill=self.style.create_shadow(fill_color),
                        outline="",
                        tags=('shadow', f'candle_{i}')
                    )
                    self.elements.append(shadow)

                    # Candle body
                    candle = self.canvas.create_rectangle(
                        x - candle_width/2, y_top,
                        x + candle_width/2, y_bottom,
                        fill=fill_color,
                        outline=outline_color,
                        width=1,
                        tags=('candle', f'candle_{i}')
                    )
                    self.elements.append(candle)

                    # Labels only after animation completes
                    if candle_progress == 1 and self.show_labels:
                        high_label = self.canvas.create_text(
                            x, y_high - 10,
                            text=f"{high:.1f}",
                            font=self.style.VALUE_FONT,
                            fill=self.style.TEXT,
                            anchor='s',
                            tags=('label', f'candle_{i}')
                        )
                        self.elements.append(high_label)

                        low_label = self.canvas.create_text(
                            x, y_low + 10,
                            text=f"{low:.1f}",
                            font=self.style.VALUE_FONT,
                            fill=self.style.TEXT,
                            anchor='n',
                            tags=('label', f'candle_{i}')
                        )
                        self.elements.append(low_label)

            except Exception as e:
                print(f"Animation update stopped due to {type(e).__name__}: {e}")
                return

            if frame < total_frames:
                self.canvas.after(20, update_animation, frame + 1, total_frames)

        total_frames = self.animation_duration // 20
        update_animation(0, total_frames)
    
    def _add_interactive_effects(self):
        """Add enhanced hover effects and tooltips"""
        tooltip = tk.Toplevel()
        tooltip.withdraw()
        tooltip.overrideredirect(True)
        tooltip.attributes('-topmost', True)
        
        tooltip_frame = ttk.Frame(tooltip, style='Tooltip.TFrame')
        tooltip_frame.pack(fill='both', expand=True)
        label = ttk.Label(tooltip_frame, style='Tooltip.TLabel', font=self.style.TOOLTIP_FONT)
        label.pack(padx=8, pady=4)
        
        style = ttk.Style()
        style.configure('Tooltip.TFrame', background=self.style.TEXT, relief='solid', borderwidth=0)
        style.configure('Tooltip.TLabel', background=self.style.TEXT, foreground=self.style.BACKGROUND,
                       font=self.style.TOOLTIP_FONT)
        
        current_highlight = None
        
        def on_motion(event):
            nonlocal current_highlight
            x, y = event.x, event.y

            # Only respond if inside chart area
            if self.padding <= x <= self.width - self.padding and self.padding <= y <= self.height - self.padding:
                candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
                candle_width = candle_spacing * self.candle_width_factor
                candle_index = int((x - self.padding) / candle_spacing)

                if 0 <= candle_index < len(self.data):
                    index, open_price, high, low, close_price = self.data[candle_index]
                    px = self._data_to_pixel_x(index, self.x_min, self.x_max)
                    y_high = self._data_to_pixel_y(high, self.y_min, self.y_max)
                    y_low = self._data_to_pixel_y(low, self.y_min, self.y_max)
                    y_open = self._data_to_pixel_y(open_price, self.y_min, self.y_max)
                    y_close = self._data_to_pixel_y(close_price, self.y_min, self.y_max)
                    y_top = min(y_open, y_close)
                    y_bottom = max(y_open, y_close)

                    # Bounding-box check: only show tooltip if cursor is inside candle bounds
                    if (px - candle_width/2 <= x <= px + candle_width/2) and (y_high <= y <= y_low):
                        if current_highlight:
                            self.canvas.delete(current_highlight)

                        highlight = self.canvas.create_rectangle(
                            px - candle_width/2 - 3, y_high - 3,
                            px + candle_width/2 + 3, y_low + 3,
                            outline=self.style.ACCENT,
                            width=2,
                            dash=(4, 2),
                            tags=('highlight',)
                        )
                        current_highlight = highlight

                        change = close_price - open_price
                        pct_change = (change / open_price * 100) if open_price != 0 else 0
                        label.config(
                            text=(
                                f"Index: {index:.1f}\n"
                                f"Open: {open_price:.2f}\n"
                                f"High: {high:.2f}\n"
                                f"Low: {low:.2f}\n"
                                f"Close: {close_price:.2f}\n"
                                f"Change: {change:.2f} ({pct_change:.1f}%)"
                            )
                        )
                        tooltip.wm_geometry(f"+{event.x_root+15}+{event.y_root-50}")
                        tooltip.deiconify()
                        tooltip.lift()
                        return  # Exit early since tooltip is shown

            # If not inside a valid candle, clean up
            if current_highlight:
                self.canvas.delete(current_highlight)
                current_highlight = None
            tooltip.withdraw()
        
        def on_leave(event):
            nonlocal current_highlight
            if current_highlight:
                self.canvas.delete(current_highlight)
                current_highlight = None
            tooltip.withdraw()
        
        self.canvas.bind('<Motion>', on_motion)
        self.canvas.bind('<Leave>', on_leave)
        self.bind('<Enter>', lambda e: tooltip.withdraw())
        
        def watchdog_hide():
            # Check if mouse is inside canvas
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            cx, cy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()

            if not (cx <= x <= cx+cw and cy <= y <= cy+ch):
                tooltip.withdraw()
                if current_highlight:
                    self.canvas.delete(current_highlight)

            # Reschedule watchdog
            self.watchdog_id = self.canvas.after(200, watchdog_hide)

        # Start watchdog once per chart
        if not self.watchdog_id:
            self.watchdog_id = self.canvas.after(200, watchdog_hide)




        
class LineChartNoLabels(LineChart):
    def __init__(self, *args, show_labels=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_labels = show_labels
        self.grid(row=0, column=0, sticky="nsew")

    def _animate_lines(self, y_min: float, y_max: float):
        """Added ability through show_labels to turn on/off labels."""

        lines = {}
        shadows = {}
        dots = {}
        labels = {}

        for idx, dataset in enumerate(self.datasets):
            if idx in self.points and len(self.points[idx]) >= 2:
                lines[idx] = self.canvas.create_line(
                    self.points[idx][0][0], self.points[idx][0][1], 
                    self.points[idx][0][0], self.points[idx][0][1],
                    fill=dataset['color'],
                    width=self.line_width,
                    tags=('line',)
                )
                shadows[idx] = self.canvas.create_line(
                    self.points[idx][0][0], self.points[idx][0][1], 
                    self.points[idx][0][0], self.points[idx][0][1],
                    fill=self.style.create_shadow(dataset['color']),
                    width=self.line_width + 2,
                    tags=('shadow',)
                )
                dots[idx] = []
                labels[idx] = []
            elif idx in self.points and len(self.points[idx]) == 1:
                x, y, data_idx = self.points[idx][0]
                fill_color = self._clamp_color(self.style.adjust_brightness(dataset['color'], 1.2))
                outline_color = self._clamp_color(self.style.adjust_brightness(dataset['color'], 0.8))
                if self.show_labels:
                    dot = self._create_shape(x, y, dataset['shape'], self.dot_radius, fill_color, outline_color)
                    label = self.canvas.create_text(
                        x, y - 15, text=f"{dataset['data'][data_idx]:,.2f}",
                        font=self.style.VALUE_FONT, fill=self.style.TEXT,
                        anchor='s', tags=('label', f'point_{idx}_0')
                    )
                    dots[idx] = [dot]
                    labels[idx] = [label]
            else:
                dots[idx] = []
                labels[idx] = []

        def ease(t):
            return t * t * (3 - 2 * t)

        def update_animation(frame: int, total_frames: int):
            if not self.canvas.winfo_exists():
                return  # widget destroyed, stop updating
            
            progress = ease(frame / total_frames)
            
            try:
                for idx, dataset in enumerate(self.datasets):
                    if idx not in lines:
                        continue
                    current_points = []
                    for i in range(len(self.points[idx])):
                        x0, y0, _ = self.points[idx][max(0, i-1)]
                        x1, y1, _ = self.points[idx][i]
                        if i == 0:
                            current_points.extend([x1, y1])
                        else:
                            interp_x = x0 + (x1 - x0) * min(1.0, progress * len(self.points[idx]) / (i + 1))
                            interp_y = y0 + (y1 - y0) * min(1.0, progress * len(self.points[idx]) / (i + 1))
                            current_points.extend([interp_x, interp_y])

                        if i < len(dots[idx]) and progress * len(self.points[idx]) >= i + 1:
                            self.canvas.coords(dots[idx][i], x1 - self.dot_radius, y1 - self.dot_radius,
                                               x1 + self.dot_radius, y1 + self.dot_radius)
                            self.canvas.coords(labels[idx][i], x1, y1 - 15)
                            self.canvas.itemconfig(dots[idx][i], state='normal')
                            self.canvas.itemconfig(labels[idx][i], state='normal')

                    self.canvas.coords(shadows[idx], *current_points)
                    self.canvas.coords(lines[idx], *current_points)

                    if frame == total_frames:
                        for i, (x, y, data_idx) in enumerate(self.points[idx]):
                            if i >= len(dots[idx]):
                                fill_color = self._clamp_color(self.style.adjust_brightness(dataset['color'], 1.2))
                                outline_color = self._clamp_color(self.style.adjust_brightness(dataset['color'], 0.8))
                                if self.show_labels: 
                                    dot = self._create_shape(x, y, dataset['shape'], self.dot_radius, fill_color, outline_color)                          
                                    label = self.canvas.create_text(
                                        x, y - 15, text=f"{dataset['data'][data_idx]:,.2f}",
                                        font=self.style.VALUE_FONT, fill=self.style.TEXT,
                                        anchor='s', tags=('label', f'point_{idx}_{i}')
                                    )
                                    dots[idx].append(dot)
                                    labels[idx].append(label)

                if frame < total_frames:
                    self.canvas.after(16, update_animation, frame + 1, total_frames)
                    
            except Exception as e:
                print(f"Animation update stopped due to {type(e).__name__}: {e}")
                return

        total_frames = self.animation_duration // 16
        update_animation(0, total_frames)