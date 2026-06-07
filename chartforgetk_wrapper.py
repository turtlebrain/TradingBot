from ChartForgeTK import CandlestickChart
from ChartForgeTK import LineChart
from typing import List, Optional, Union, Tuple, Dict
import math
import tkinter as tk
from tkinter import ttk

# Performance thresholds (see chart_performance.py for Phase 3 engine notes)
ANIMATION_BAR_THRESHOLD = 400
SHADOW_BAR_THRESHOLD = 500
LABEL_BAR_THRESHOLD = 200
LINE_ANIMATION_THRESHOLD = 400


def _nice_step(data_range, num_ticks=6):
    """Return a human-friendly tick step size for the given data range."""
    if data_range <= 0:
        return 1
    raw = data_range / num_ticks
    mag = 10 ** math.floor(math.log10(raw))
    norm = raw / mag
    if norm <= 1:
        return mag
    elif norm <= 2:
        return 2 * mag
    elif norm <= 5:
        return 5 * mag
    return 10 * mag


def _tick_label(value, step):
    """Format a tick value with appropriate decimal places."""
    if step >= 1:
        return f"{value:,.0f}"
    decimals = max(0, -math.floor(math.log10(step))) + 1
    return f"{value:,.{decimals}f}"


class CandlestickChartNoLabels(CandlestickChart):
    def __init__(self, *args, show_labels=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_labels = show_labels
        self.grid(row=0, column=0, sticky="nsew")
        self.watchdog_id = None
        self._interactive_ready = False
        self._animation_after_id = None
        self._last_candle_items = None
        self._y_padding = 0.0

    def plot(self, data: List[Tuple[float, float, float, float, float]], title: str = "Candlestick Chart", animation_flag: bool = False):
        """Plot an improved candlestick chart with (index, open, high, low, close) data"""
        if not data:
            raise ValueError("Data cannot be empty")
        if not all(isinstance(d, tuple) and len(d) == 5 and
                  all(isinstance(v, (int, float)) for v in d) for d in data):
            raise TypeError("Data must be a list of (index, open, high, low, close) number tuples")

        self._cancel_animation()

        self.timestamps = getattr(self, "timestamps", None)
        self.data = sorted(data, key=lambda x: x[0])

        indices, opens, highs, lows, closes = zip(*self.data)
        self.x_min, self.x_max = min(indices), max(indices)
        raw_y_min, raw_y_max = min(lows), max(highs)
        x_padding = (self.x_max - self.x_min) * 0.1 or 1
        self._y_padding = (raw_y_max - raw_y_min) * 0.1 or 1
        self.x_min -= x_padding
        self.x_max += x_padding
        self.y_min = raw_y_min - self._y_padding
        self.y_max = raw_y_max + self._y_padding

        self.title = title
        self.x_label = "Time/Index"
        self.y_label = "Price"

        self.canvas.delete('all')
        self.elements.clear()
        self._last_candle_items = None

        self._draw_axes(self.x_min, self.x_max, self.y_min, self.y_max)

        if len(self.data) > ANIMATION_BAR_THRESHOLD:
            self._draw_candles_static()
        elif animation_flag:
            self._animate_candles(animate_last_only=True)
        else:
            self._animate_candles(animate_last_only=False)

        self._add_interactive_effects()

    def _cancel_animation(self):
        if self._animation_after_id is not None:
            try:
                self.canvas.after_cancel(self._animation_after_id)
            except tk.TclError:
                pass
            self._animation_after_id = None

    def _draw_shadows(self) -> bool:
        return len(self.data) <= SHADOW_BAR_THRESHOLD

    def _draw_price_labels(self) -> bool:
        return self.show_labels and len(self.data) <= LABEL_BAR_THRESHOLD

    def _candle_geometry(self, index, open_price, high, low, close_price, candle_width, candle_progress=1.0):
        x = self._data_to_pixel_x(index, self.x_min, self.x_max)
        y_open = self._data_to_pixel_y(open_price, self.y_min, self.y_max)
        y_high = self._data_to_pixel_y(high, self.y_min, self.y_max)
        y_low = self._data_to_pixel_y(low, self.y_min, self.y_max)
        y_close = self._data_to_pixel_y(close_price, self.y_min, self.y_max)

        fill_color = "#4CAF50" if close_price >= open_price else "#F44336"
        outline_color = self.style.adjust_brightness(fill_color, 0.8)

        y_mid = (y_open + y_close) / 2
        candle_height = abs(y_close - y_open) * candle_progress
        if candle_height < 1:
            candle_height = 1
        y_top = y_mid - candle_height / 2
        y_bottom = y_mid + candle_height / 2

        y_mid_wick = (y_high + y_low) / 2
        half_wick_length = (y_low - y_high) / 2 * candle_progress

        return {
            "x": x,
            "y_top": y_top,
            "y_bottom": y_bottom,
            "y_high": y_high,
            "y_low": y_low,
            "wick_top": y_mid_wick - half_wick_length,
            "wick_bottom": y_mid_wick + half_wick_length,
            "fill_color": fill_color,
            "outline_color": outline_color,
            "candle_width": candle_width,
        }

    def _create_candle_items(self, i, geom, store_elements=True, store_last=False):
        x = geom["x"]
        candle_width = geom["candle_width"]
        items = []

        wick = self.canvas.create_line(
            x, geom["wick_top"],
            x, geom["wick_bottom"],
            fill=self.style.TEXT_SECONDARY,
            width=self.wick_width,
            tags=('wick', f'candle_{i}')
        )
        items.append(wick)

        if self._draw_shadows():
            shadow = self.canvas.create_rectangle(
                x - candle_width / 2 + 2, geom["y_top"] + 2,
                x + candle_width / 2 + 2, geom["y_bottom"] + 2,
                fill=self.style.create_shadow(geom["fill_color"]),
                outline="",
                tags=('shadow', f'candle_{i}')
            )
            items.append(shadow)

        candle = self.canvas.create_rectangle(
            x - candle_width / 2, geom["y_top"],
            x + candle_width / 2, geom["y_bottom"],
            fill=geom["fill_color"],
            outline=geom["outline_color"],
            width=1,
            tags=('candle', f'candle_{i}')
        )
        items.append(candle)

        if self._draw_price_labels():
            high_label = self.canvas.create_text(
                x, geom["y_high"] - 10,
                text=f"{self.data[i][2]:.1f}",
                font=self.style.VALUE_FONT,
                fill=self.style.TEXT,
                anchor='s',
                tags=('label', f'candle_{i}')
            )
            low_label = self.canvas.create_text(
                x, geom["y_low"] + 10,
                text=f"{self.data[i][3]:.1f}",
                font=self.style.VALUE_FONT,
                fill=self.style.TEXT,
                anchor='n',
                tags=('label', f'candle_{i}')
            )
            items.extend([high_label, low_label])

        if store_elements:
            self.elements.extend(items)
        if store_last:
            self._last_candle_items = tuple(items[:3])
        return items

    def _draw_candles_static(self):
        candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
        candle_width = candle_spacing * self.candle_width_factor

        for i, (index, open_price, high, low, close_price) in enumerate(self.data):
            geom = self._candle_geometry(
                index, open_price, high, low, close_price, candle_width, candle_progress=1.0
            )
            store_last = i == len(self.data) - 1
            self._create_candle_items(i, geom, store_elements=True, store_last=store_last)

    def update_last_candle(self, candle_data: Tuple[float, float, float, float, float], index: int) -> bool:
        """Update only the last candle when OHLC changes in place. Returns True on success."""
        if not self.data or index != len(self.data) - 1:
            return False

        _, open_price, high, low, close_price = candle_data
        if high > self.y_max or low < self.y_min:
            return False

        self.data[-1] = candle_data
        items = self._last_candle_items
        if not items or len(items) < 2:
            return False

        candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
        candle_width = candle_spacing * self.candle_width_factor
        geom = self._candle_geometry(
            candle_data[0], open_price, high, low, close_price, candle_width, candle_progress=1.0
        )

        wick_id = items[0]
        body_id = items[2] if self._draw_shadows() and len(items) >= 3 else items[-1]

        self.canvas.coords(wick_id, geom["x"], geom["wick_top"], geom["x"], geom["wick_bottom"])
        self.canvas.coords(
            body_id,
            geom["x"] - candle_width / 2, geom["y_top"],
            geom["x"] + candle_width / 2, geom["y_bottom"],
        )
        if self._draw_shadows() and len(items) >= 3:
            shadow_id = items[1]
            self.canvas.coords(
                shadow_id,
                geom["x"] - candle_width / 2 + 2, geom["y_top"] + 2,
                geom["x"] + candle_width / 2 + 2, geom["y_bottom"] + 2,
            )
        self.canvas.itemconfig(body_id, fill=geom["fill_color"], outline=geom["outline_color"])

        return True

    def _draw_axes(self, x_min: float, x_max: float, y_min: float, y_max: float):
        """Override: draw axes but replace numeric x-ticks with timestamp labels."""
        self.x_min, self.x_max = x_min, x_max
        self.y_min, self.y_max = y_min, y_max

        self._draw_grid(x_min, x_max, y_min, y_max)

        self.canvas.create_line(
            self.padding, self.padding,
            self.padding, self.height - self.padding,
            fill=self.style.AXIS_COLOR,
            width=self.style.AXIS_WIDTH,
            capstyle=tk.ROUND
        )

        y_zero = 0 if y_min <= 0 <= y_max else y_min
        axis_y = self._data_to_pixel_y(y_zero, y_min, y_max)

        self.canvas.create_line(
            self.padding, axis_y,
            self.width - self.padding, axis_y,
            fill=self.style.AXIS_COLOR,
            width=self.style.AXIS_WIDTH,
            capstyle=tk.ROUND
        )

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
            skip_x_ticks = True
        else:
            skip_x_ticks = False

        self._draw_ticks(x_min, x_max, y_min, y_max, skip_x_ticks=skip_x_ticks)

        if self.title:
            self.canvas.create_text(
                self.width / 2, self.padding / 2,
                text=self.title,
                font=self.style.TITLE_FONT,
                fill=self.style.TEXT,
                anchor='center'
            )

        if self.x_label:
            self.canvas.create_text(
                self.width / 2, self.height - self.padding / 3,
                text=self.x_label,
                font=self.style.LABEL_FONT,
                fill=self.style.TEXT_SECONDARY,
                anchor='center'
            )

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
        num_ticks = 6

        y_range = y_max - y_min
        if y_range > 0:
            step = _nice_step(y_range, num_ticks)
            tick = math.ceil(y_min / step) * step
            while tick <= y_max:
                py = self._data_to_pixel_y(tick, y_min, y_max)
                self.canvas.create_line(
                    self.padding - 5, py, self.padding, py,
                    fill=self.style.AXIS_COLOR, width=1,
                )
                self.canvas.create_text(
                    self.padding - 8, py,
                    text=_tick_label(tick, step),
                    font=("Arial", 9),
                    fill=self.style.TEXT_SECONDARY,
                    anchor="e",
                )
                tick += step

        if not skip_x_ticks:
            x_range = x_max - x_min
            if x_range > 0:
                step = _nice_step(x_range, num_ticks)
                y_zero = 0 if y_min <= 0 <= y_max else y_min
                axis_y = self._data_to_pixel_y(y_zero, y_min, y_max)
                tick = math.ceil(x_min / step) * step
                while tick <= x_max:
                    px = self._data_to_pixel_x(tick, x_min, x_max)
                    self.canvas.create_line(
                        px, axis_y, px, axis_y + 5,
                        fill=self.style.AXIS_COLOR, width=1,
                    )
                    self.canvas.create_text(
                        px, axis_y + 10,
                        text=_tick_label(tick, step),
                        font=("Arial", 9),
                        fill=self.style.TEXT_SECONDARY,
                        anchor="n",
                    )
                    tick += step

    def _animate_candles(self, animate_last_only: bool = False):
        def ease(t):
            return t * t * (3 - 2 * t)

        candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
        candle_width = candle_spacing * self.candle_width_factor

        def update_animation(frame: int, total_frames: int):
            if not self.canvas.winfo_exists():
                return

            progress = ease(frame / total_frames) if total_frames else 1.0

            try:
                for item in self.elements:
                    self.canvas.delete(item)
                self.elements.clear()
                self._last_candle_items = None

                last_index = len(self.data) - 1

                for i, (index, open_price, high, low, close_price) in enumerate(self.data):
                    if animate_last_only and i != last_index:
                        candle_progress = 1.0
                    else:
                        candle_progress = progress

                    geom = self._candle_geometry(
                        index, open_price, high, low, close_price, candle_width, candle_progress
                    )
                    store_last = i == last_index and candle_progress >= 1.0
                    self._create_candle_items(i, geom, store_elements=True, store_last=store_last)

            except Exception as e:
                print(f"Animation update stopped due to {type(e).__name__}: {e}")
                return

            if frame < total_frames:
                self._animation_after_id = self.canvas.after(
                    20, update_animation, frame + 1, total_frames
                )
            else:
                self._animation_after_id = None

        total_frames = max(1, self.animation_duration // 20)
        update_animation(0, total_frames)

    def _add_interactive_effects(self):
        """Add enhanced hover effects and tooltips (bound once per chart instance)."""
        if self._interactive_ready:
            return
        self._interactive_ready = True

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

            if self.padding <= x <= self.width - self.padding and self.padding <= y <= self.height - self.padding:
                candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
                candle_width = candle_spacing * self.candle_width_factor
                candle_index = int((x - self.padding) / candle_spacing)

                if 0 <= candle_index < len(self.data):
                    index, open_price, high, low, close_price = self.data[candle_index]
                    px = self._data_to_pixel_x(index, self.x_min, self.x_max)
                    y_high = self._data_to_pixel_y(high, self.y_min, self.y_max)
                    y_low = self._data_to_pixel_y(low, self.y_min, self.y_max)

                    if (px - candle_width / 2 <= x <= px + candle_width / 2) and (y_high <= y <= y_low):
                        if current_highlight:
                            self.canvas.delete(current_highlight)

                        highlight = self.canvas.create_rectangle(
                            px - candle_width / 2 - 3, y_high - 3,
                            px + candle_width / 2 + 3, y_low + 3,
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
                        tooltip.wm_geometry(f"+{event.x_root + 15}+{event.y_root - 50}")
                        tooltip.deiconify()
                        tooltip.lift()
                        return

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
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            cx, cy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
            cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()

            if not (cx <= x <= cx + cw and cy <= y <= cy + ch):
                tooltip.withdraw()
                if current_highlight:
                    self.canvas.delete(current_highlight)

            self.watchdog_id = self.canvas.after(200, watchdog_hide)

        if not self.watchdog_id:
            self.watchdog_id = self.canvas.after(200, watchdog_hide)


class LineChartNoLabels(LineChart):
    def __init__(self, *args, show_labels=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_labels = show_labels
        self.grid(row=0, column=0, sticky="nsew")
        self._interactive_ready = False
        self._animation_after_id = None

    def plot(self, data: Union[List[float], List[Dict[str, Union[List[float], str]]]],
             x_min: Optional[float] = None, x_max: Optional[float] = None,
             y_min: Optional[float] = None, y_max: Optional[float] = None):
        if not data:
            raise ValueError("Data cannot be empty")

        self._cancel_animation()
        self.timestamps = getattr(self, "timestamps", None)
        self.zoom_level = 1.0
        self.zoom_center_x = None
        self.zoom_center_y = None

        if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
            self.datasets = [{
                'data': data,
                'color': self._clamp_color(self.style.ACCENT),
                'shape': 'circle',
                'label': 'Line 1'
            }]
        else:
            self.datasets = []
            for dataset in data:
                if 'data' not in dataset or not dataset['data']:
                    raise ValueError("Each dataset must contain non-empty 'data'")
                if not all(isinstance(x, (int, float)) for x in dataset['data']):
                    raise TypeError("All data points must be numbers")

                self.datasets.append({
                    'data': dataset['data'],
                    'color': self._clamp_color(dataset.get('color', self.style.ACCENT)),
                    'shape': dataset.get('shape', 'circle') if dataset.get('shape') in self.shapes else 'circle',
                    'label': dataset.get('label', f'Line {len(self.datasets) + 1}')
                })

        all_data = [x for ds in self.datasets for x in ds['data']]
        full_x_min, full_x_max = 0, max(len(ds['data']) for ds in self.datasets) - 1
        full_y_min, full_y_max = min(all_data), max(all_data)
        padding = (full_y_max - full_y_min) * 0.1 or 1
        full_y_min -= padding
        full_y_max += padding

        if x_min is None or x_max is None or y_min is None or y_max is None:
            x_range = (full_x_max - full_x_min) / self.zoom_level
            y_range = (full_y_max - full_y_min) / self.zoom_level
            if self.zoom_center_x is None:
                self.zoom_center_x = (full_x_max + full_x_min) / 2
            if self.zoom_center_y is None:
                self.zoom_center_y = (full_y_max + full_y_min) / 2

            x_min = max(full_x_min, self.zoom_center_x - x_range / 2)
            x_max = min(full_x_max, self.zoom_center_x + x_range / 2)
            y_min = max(full_y_min, self.zoom_center_y - y_range / 2)
            y_max = min(full_y_max, self.zoom_center_y + y_range / 2)

        if y_max <= y_min:
            mid = (full_y_max + full_y_min) / 2
            y_min, y_max = mid - 1, mid + 1
        if x_max <= x_min:
            mid = (full_x_max + full_x_min) / 2
            x_min, x_max = mid - 0.5, mid + 0.5

        self.canvas.delete('all')
        self._draw_axes(x_min, x_max, y_min, y_max)

        self.points = {}
        for idx, dataset in enumerate(self.datasets):
            self.points[idx] = []
            for i, y in enumerate(dataset['data']):
                if x_min <= i <= x_max and y_min <= y <= y_max:
                    x = self._data_to_pixel_x(i, x_min, x_max)
                    y_px = self._data_to_pixel_y(y, y_min, y_max)
                    self.points[idx].append((x, y_px, i))

        max_points = max((len(ds['data']) for ds in self.datasets), default=0)
        if max_points > LINE_ANIMATION_THRESHOLD:
            self._draw_lines_static(y_min, y_max)
        else:
            self._animate_lines(y_min, y_max)

        self._add_interactive_effects()

        for bar in self.bars[:]:
            self.canvas.delete(bar['id'])
            if bar['label_id']:
                self.canvas.delete(bar['label_id'])
            self.add_bar(bar['orientation'], bar['value'], bar['color'], bar['width'], bar['dash'], bar['label'])

    def _cancel_animation(self):
        if self._animation_after_id is not None:
            try:
                self.canvas.after_cancel(self._animation_after_id)
            except tk.TclError:
                pass
            self._animation_after_id = None

    def _draw_lines_static(self, y_min: float, y_max: float):
        for idx, dataset in enumerate(self.datasets):
            if idx not in self.points or len(self.points[idx]) < 2:
                continue
            coords = []
            for x, y, _ in self.points[idx]:
                coords.extend([x, y])
            self.canvas.create_line(
                *coords,
                fill=self.style.create_shadow(dataset['color']),
                width=self.line_width + 2,
                tags=('shadow',),
            )
            self.canvas.create_line(
                *coords,
                fill=dataset['color'],
                width=self.line_width,
                tags=('line',),
            )

    def _draw_axes(self, x_min: float, x_max: float, y_min: float, y_max: float):
        self.x_min, self.x_max = x_min, x_max
        self.y_min, self.y_max = y_min, y_max

        self._draw_grid(x_min, x_max, y_min, y_max)

        self.canvas.create_line(
            self.padding, self.padding,
            self.padding, self.height - self.padding,
            fill=self.style.AXIS_COLOR,
            width=self.style.AXIS_WIDTH,
            capstyle=tk.ROUND
        )

        y_zero = 0 if y_min <= 0 <= y_max else y_min
        axis_y = self._data_to_pixel_y(y_zero, y_min, y_max)

        self.canvas.create_line(
            self.padding, axis_y,
            self.width - self.padding, axis_y,
            fill=self.style.AXIS_COLOR,
            width=self.style.AXIS_WIDTH,
            capstyle=tk.ROUND
        )

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
            skip_x_ticks = True
        else:
            skip_x_ticks = False

        self._draw_ticks(x_min, x_max, y_min, y_max, skip_x_ticks=skip_x_ticks)

        if self.title:
            self.canvas.create_text(
                self.width / 2, self.padding / 2,
                text=self.title,
                font=self.style.TITLE_FONT,
                fill=self.style.TEXT,
                anchor='center'
            )

        if self.x_label:
            self.canvas.create_text(
                self.width / 2, self.height - self.padding / 3,
                text=self.x_label,
                font=self.style.LABEL_FONT,
                fill=self.style.TEXT_SECONDARY,
                anchor='center'
            )

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
        num_ticks = 6

        y_range = y_max - y_min
        if y_range > 0:
            step = _nice_step(y_range, num_ticks)
            tick = math.ceil(y_min / step) * step
            while tick <= y_max:
                py = self._data_to_pixel_y(tick, y_min, y_max)
                self.canvas.create_line(
                    self.padding - 5, py, self.padding, py,
                    fill=self.style.AXIS_COLOR, width=1,
                )
                self.canvas.create_text(
                    self.padding - 8, py,
                    text=_tick_label(tick, step),
                    font=("Arial", 9),
                    fill=self.style.TEXT_SECONDARY,
                    anchor="e",
                )
                tick += step

        if not skip_x_ticks:
            x_range = x_max - x_min
            if x_range > 0:
                step = _nice_step(x_range, num_ticks)
                y_zero = 0 if y_min <= 0 <= y_max else y_min
                axis_y = self._data_to_pixel_y(y_zero, y_min, y_max)
                tick = math.ceil(x_min / step) * step
                while tick <= x_max:
                    px = self._data_to_pixel_x(tick, x_min, x_max)
                    self.canvas.create_line(
                        px, axis_y, px, axis_y + 5,
                        fill=self.style.AXIS_COLOR, width=1,
                    )
                    self.canvas.create_text(
                        px, axis_y + 10,
                        text=_tick_label(tick, step),
                        font=("Arial", 9),
                        fill=self.style.TEXT_SECONDARY,
                        anchor="n",
                    )
                    tick += step

    def _animate_lines(self, y_min: float, y_max: float):
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
                if self.show_labels and len(dataset['data']) <= LABEL_BAR_THRESHOLD:
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
                return

            progress = ease(frame / total_frames)

            try:
                for idx, dataset in enumerate(self.datasets):
                    if idx not in lines:
                        continue
                    current_points = []
                    for i in range(len(self.points[idx])):
                        x0, y0, _ = self.points[idx][max(0, i - 1)]
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

                    if frame == total_frames and self.show_labels and len(dataset['data']) <= LABEL_BAR_THRESHOLD:
                        for i, (x, y, data_idx) in enumerate(self.points[idx]):
                            if i >= len(dots[idx]):
                                fill_color = self._clamp_color(self.style.adjust_brightness(dataset['color'], 1.2))
                                outline_color = self._clamp_color(self.style.adjust_brightness(dataset['color'], 0.8))
                                dot = self._create_shape(x, y, dataset['shape'], self.dot_radius, fill_color, outline_color)
                                label = self.canvas.create_text(
                                    x, y - 15, text=f"{dataset['data'][data_idx]:,.2f}",
                                    font=self.style.VALUE_FONT, fill=self.style.TEXT,
                                    anchor='s', tags=('label', f'point_{idx}_{i}')
                                )
                                dots[idx].append(dot)
                                labels[idx].append(label)

                if frame < total_frames:
                    self._animation_after_id = self.canvas.after(
                        16, update_animation, frame + 1, total_frames
                    )
                else:
                    self._animation_after_id = None

            except Exception as e:
                print(f"Animation update stopped due to {type(e).__name__}: {e}")
                return

        total_frames = max(1, self.animation_duration // 16)
        update_animation(0, total_frames)

    def _add_interactive_effects(self):
        if self._interactive_ready:
            return
        self._interactive_ready = True
        super()._add_interactive_effects()
        super()._add_interactive_effects()
