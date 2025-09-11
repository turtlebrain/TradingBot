from ChartForgeTK import CandlestickChart

class CandlestickChartNoLabels(CandlestickChart):
    def __init__(self, *args, show_labels=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_labels = show_labels

    def _animate_candles(self):
        """Draw candlesticks without high/low labels."""
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