from ChartForgeTK import CandlestickChart
from ChartForgeTK import LineChart
from typing import List, Tuple

class CandlestickChartNoLabels(CandlestickChart):
    def __init__(self, *args, show_labels=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_labels = show_labels
        self.grid(row=0, column=0, sticky="nsew")

    def plot(self, data: List[Tuple[float, float, float, float, float]], title: str = "Candlestick Chart"):
        """Plot an improved candlestick chart with (index, open, high, low, close) data"""
        if not data:
            raise ValueError("Data cannot be empty")
        if not all(isinstance(d, tuple) and len(d) == 5 and 
                  all(isinstance(v, (int, float)) for v in d) for d in data):
            raise TypeError("Data must be a list of (index, open, high, low, close) number tuples")
            
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
        self._animate_candles()
        self._add_interactive_effects()

    def _animate_candles(self):
        """Added ability through show_labels to turn on/off high/low labels."""
        def ease(t):
            return t * t * (3 - 2 * t)

        candle_spacing = (self.width - 2 * self.padding) / (len(self.data) if len(self.data) > 1 else 1)
        candle_width = candle_spacing * self.candle_width_factor

        def update_animation(frame: int, total_frames: int):
            progress = ease(frame / total_frames)

            for item in self.elements:
                self.canvas.delete(item)
            self.elements.clear()

            for i, (index, open_price, high, low, close_price) in enumerate(self.data):
                x = self._data_to_pixel_x(index, self.x_min, self.x_max)
                y_open = self._data_to_pixel_y(open_price, self.y_min, self.y_max)
                y_high = self._data_to_pixel_y(high, self.y_min, self.y_max)
                y_low = self._data_to_pixel_y(low, self.y_min, self.y_max)
                y_close = self._data_to_pixel_y(close_price, self.y_min, self.y_max)

                fill_color = "#4CAF50" if close_price >= open_price else "#F44336"
                outline_color = self.style.adjust_brightness(fill_color, 0.8)

                y_mid = (y_open + y_close) / 2
                candle_height = abs(y_close - y_open) * progress
                if candle_height < 1:
                    candle_height = 1
                y_top = y_mid - candle_height / 2
                y_bottom = y_mid + candle_height / 2
                
                y_mid_wick = (y_high + y_low) / 2
                half_wick_length = (y_low - y_high) / 2 * progress
                wick = self.canvas.create_line(
                    x, y_mid_wick - half_wick_length,
                    x, y_mid_wick + half_wick_length,
                    fill=self.style.TEXT_SECONDARY,
                    width=self.wick_width,
                    tags=('wick', f'candle_{i}')
                )
                self.elements.append(wick)

                shadow = self.canvas.create_rectangle(
                    x - candle_width/2 + 2, y_top + 2,
                    x + candle_width/2 + 2, y_bottom + 2,
                    fill=self.style.create_shadow(fill_color),
                    outline="",
                    tags=('shadow', f'candle_{i}')
                )
                self.elements.append(shadow)

                candle = self.canvas.create_rectangle(
                    x - candle_width/2, y_top,
                    x + candle_width/2, y_bottom,
                    fill=fill_color,
                    outline=outline_color,
                    width=1,
                    tags=('candle', f'candle_{i}')
                )
                self.elements.append(candle)

                if progress == 1 and self.show_labels is True:
                    # High label above wick
                    high_label = self.canvas.create_text(
                        x, y_high - 10,
                        text=f"{high:.1f}",
                        font=self.style.VALUE_FONT,
                        fill=self.style.TEXT,
                        anchor='s',
                        tags=('label', f'candle_{i}')
                    )
                    self.elements.append(high_label)
                    # Low label below wick
                    low_label = self.canvas.create_text(
                        x, y_low + 10,
                        text=f"{low:.1f}",
                        font=self.style.VALUE_FONT,
                        fill=self.style.TEXT,
                        anchor='n',
                        tags=('label', f'candle_{i}')
                    )
                    self.elements.append(low_label)

            if frame < total_frames:
                self.canvas.after(20, update_animation, frame + 1, total_frames)

        total_frames = self.animation_duration // 20
        update_animation(0, total_frames)
        
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
            progress = ease(frame / total_frames)
            
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

        total_frames = self.animation_duration // 16
        update_animation(0, total_frames)