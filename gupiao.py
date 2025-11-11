# interactive_kline.py
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import pandas as pd
import mplfinance as mpf
import re
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import os
import platform


def setup_chinese_font():
    """设置中文字体 - 增强版本"""
    try:
        # 根据操作系统选择字体策略
        system = platform.system()

        if system == "Windows":
            # Windows 系统字体路径
            font_paths = [
                "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
                "C:/Windows/Fonts/simhei.ttf",  # 黑体
                "C:/Windows/Fonts/simsun.ttc",  # 宋体
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    # 直接使用字体文件
                    font_prop = font_manager.FontProperties(fname=font_path)
                    font_name = font_prop.get_name()
                    matplotlib.rcParams['font.family'] = [font_name, 'DejaVu Sans']
                    matplotlib.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
                    print(f"使用字体文件: {font_path} -> {font_name}")
                    break
            else:
                # 回退到系统字体选择
                select_system_font()

        elif system == "Darwin":  # macOS
            font_paths = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/System/Library/Fonts/STHeiti Medium.ttc",
            ]
            for font_path in font_paths:
                if os.path.exists(font_path):
                    font_prop = font_manager.FontProperties(fname=font_path)
                    font_name = font_prop.get_name()
                    matplotlib.rcParams['font.family'] = [font_name, 'DejaVu Sans']
                    matplotlib.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
                    print(f"使用字体文件: {font_path} -> {font_name}")
                    break
            else:
                select_system_font()

        else:  # Linux 和其他系统
            select_system_font()

    except Exception as e:
        print(f"字体设置出错: {e}")
        select_system_font()

    matplotlib.rcParams['axes.unicode_minus'] = False


def select_system_font():
    """选择系统字体"""
    font_candidates = [
        'Microsoft YaHei', 'SimHei', 'KaiTi', 'SimSun',
        'STSong', 'AppleGothic', 'Arial Unicode MS', 'DejaVu Sans'
    ]

    available_fonts = set([f.name for f in font_manager.fontManager.ttflist])

    selected_font = None
    for font in font_candidates:
        if font in available_fonts:
            selected_font = font
            break

    if selected_font:
        matplotlib.rcParams['font.family'] = [selected_font, 'DejaVu Sans']
        matplotlib.rcParams['font.sans-serif'] = [selected_font, 'DejaVu Sans']
        print(f"已设置中文字体: {selected_font}")
    else:
        matplotlib.rcParams['font.family'] = ['DejaVu Sans']
        matplotlib.rcParams['font.sans-serif'] = ['DejaVu Sans']
        print("警告: 未找到中文字体，中文可能显示为方框")


def get_chinese_font_prop():
    """获取中文字体属性"""
    current_font = matplotlib.rcParams['font.sans-serif'][0]
    if current_font != 'DejaVu Sans':
        return font_manager.FontProperties(family=current_font)
    return None


# 在程序开始处调用字体设置
setup_chinese_font()

API_URL = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={datalen}")


def validate_stock_code(code: str) -> str | None:
    code = code.strip().lower()
    if re.match(r"^(sh|sz)\d{6}$", code):
        return code
    return None


def fetch_daily_kline(symbol: str, datalen: int = 120) -> pd.DataFrame | None:
    """
    从新浪获取日线（scale=240）原始 K 线数据并返回 DataFrame（datetime 索引）。
    如果获取失败返回 None。
    """
    url = API_URL.format(symbol=symbol, scale=240, datalen=datalen)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
        if not raw:
            return None
        df = pd.DataFrame(raw)
        # 有些字段可能为字符串，转换数值
        for col in ('open', 'high', 'low', 'close', 'volume'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            else:
                df[col] = pd.NA
        df['datetime'] = pd.to_datetime(df['day'])
        df.set_index('datetime', inplace=True)
        # 保留必须列并按时间升序（API 返回最新在后/前不稳定，统一升序）
        df = df.sort_index()
        df = df[['open', 'high', 'low', 'close', 'volume']]
        return df
    except Exception as e:
        print("请求失败:", e)
        return None


def resample_ohlc(df_daily: pd.DataFrame, period: str) -> pd.DataFrame:
    """
    使用 pandas 对日线重采样为 weekly/monthly。
    period: 'D' (daily - 返回原始), 'W' 或 'M'
    """
    if period == 'D':
        return df_daily.copy()
    elif period in ('W', 'M'):
        ohlc = df_daily[['open', 'high', 'low', 'close']].resample(period).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last'
        }).dropna()
        volume = df_daily['volume'].resample(period).sum().reindex(ohlc.index)
        ohlc['volume'] = volume
        return ohlc
    else:
        raise ValueError("unsupported period")


def compute_latest_stats(df: pd.DataFrame):
    """
    计算最新一根 K 线以及与前一根的涨跌等信息
    返回字典
    """
    if df.shape[0] < 2:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close_diff = float(last['close'] - prev['close'])
    change_pct = (close_diff / float(prev['close'])) * 100 if prev['close'] != 0 else 0.0
    # 这里涨速以小时为单位近似：若原始为日线，则间隔天数
    time_diff_days = (df.index[-1] - df.index[-2]).total_seconds() / (3600 * 24)
    change_speed = change_pct / (time_diff_days * 24) if time_diff_days > 0 else 0.0
    return {
        '日期': df.index[-1],
        '开盘价': float(last['open']),
        '最高价': float(last['high']),
        '最低价': float(last['low']),
        '收盘价': float(last['close']),
        '成交量': float(last['volume']),
        '涨跌额': close_diff,
        '涨跌幅': change_pct,
        '涨速': change_speed
    }


class KlineApp:
    def __init__(self, root):
        self.root = root
        root.title("新浪 K 线交互查看器")
        root.geometry("1000x700")

        # 顶部输入区
        top_frame = ttk.Frame(root)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        ttk.Label(top_frame, text="股票代码（示例：sz000001 / sh601006）:").pack(side=tk.LEFT)
        self.code_var = tk.StringVar(value="sz000001")
        self.entry = ttk.Entry(top_frame, textvariable=self.code_var, width=15)
        self.entry.pack(side=tk.LEFT, padx=6)

        self.fetch_btn = ttk.Button(top_frame, text="获取并绘图", command=self.on_fetch)
        self.fetch_btn.pack(side=tk.LEFT, padx=6)

        # 图表类型单选
        self.period_var = tk.StringVar(value='D')
        ttk.Radiobutton(top_frame, text="日K", variable=self.period_var, value='D').pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(top_frame, text="周K", variable=self.period_var, value='W').pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(top_frame, text="月K", variable=self.period_var, value='M').pack(side=tk.LEFT, padx=6)

        # 状态和基本信息区
        info_frame = ttk.Frame(root)
        info_frame.pack(side=tk.TOP, fill=tk.X, padx=8)
        self.status_label = ttk.Label(info_frame, text="状态: 空闲")
        self.status_label.pack(side=tk.LEFT)

        # 右侧显示最新行情详情（多行标签）
        self.info_text = tk.Text(root, height=5, width=60)
        self.info_text.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0))
        self.info_text.configure(state='disabled')

        # 绘图区
        self.plot_frame = ttk.Frame(root)
        self.plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.canvas_widget = None  # FigureCanvasTkAgg 对象

        # 存数据
        self.current_df = None
        self.current_symbol = None

    def set_status(self, txt: str):
        self.status_label.config(text=f"状态: {txt}")

    def show_info(self, text: str):
        self.info_text.configure(state='normal')
        self.info_text.delete('1.0', tk.END)
        self.info_text.insert(tk.END, text)
        self.info_text.configure(state='disabled')

    def on_fetch(self):
        code = self.code_var.get()
        symbol = validate_stock_code(code)
        if not symbol:
            messagebox.showwarning("格式错误", "股票代码格式错误（示例：sz000001 / sh601006）")
            return
        # 启动线程执行网络请求 + 绘图
        self.fetch_btn.config(state=tk.DISABLED)
        self.set_status("正在获取数据...")
        thr = threading.Thread(target=self._fetch_and_plot, args=(symbol,), daemon=True)
        thr.start()

    def _fetch_and_plot(self, symbol):
        try:
            df_daily = fetch_daily_kline(symbol, datalen=240)
            if df_daily is None or df_daily.empty:
                self.root.after(0, lambda: messagebox.showerror("错误", "未能获取到行情数据"))
                self.root.after(0, lambda: self.set_status("空闲"))
                self.root.after(0, lambda: self.fetch_btn.config(state=tk.NORMAL))
                return

            # 根据选择重采样
            period = self.period_var.get()
            df = resample_ohlc(df_daily, period)
            if df is None or df.empty:
                self.root.after(0, lambda: messagebox.showerror("错误", "重采样后无数据"))
                return

            # 计算最新行情
            stats = compute_latest_stats(df)
            info_lines = [
                f"股票代码: {symbol.upper()}",
            ]
            if stats:
                info_lines += [
                    f"日期: {stats['日期']}",
                    f"开盘价: {stats['开盘价']:.4f}",
                    f"最高价: {stats['最高价']:.4f}",
                    f"最低价: {stats['最低价']:.4f}",
                    f"收盘价: {stats['收盘价']:.4f}",
                    f"成交量: {stats['成交量']:.4f}",
                    f"涨跌额: {stats['涨跌额']:.4f}",
                    f"涨跌幅: {stats['涨跌幅']:.4f}%",
                    f"涨速: {stats['涨速']:.6f} (%/小时)",
                ]
            else:
                info_lines.append("可用数据不足，无法计算最新行情。")

            # 保存数据并在主线程更新 UI 和绘图
            self.current_df = df
            self.current_symbol = symbol
            self.root.after(0, lambda: self.show_info("\n".join(info_lines)))
            self.root.after(0, lambda: self.set_status("绘制图表中..."))
            self.root.after(0, lambda: self._draw_mpf(df, symbol))
        except Exception as e:
            print("后台错误:", e)
            self.root.after(0, lambda: messagebox.showerror("错误", f"处理失败: {e}"))
        finally:
            self.root.after(0, lambda: self.set_status("空闲"))
            self.root.after(0, lambda: self.fetch_btn.config(state=tk.NORMAL))

    def _draw_mpf(self, df: pd.DataFrame, symbol: str):
        # 在绘图前重新确保字体设置
        setup_chinese_font()

        # 获取中文字体属性
        chinese_font_prop = get_chinese_font_prop()

        # 通达信配色：红涨绿跌
        market_style = mpf.make_mpf_style(
            base_mpl_style="classic",
            marketcolors=mpf.make_marketcolors(
                up='red',
                down='green',
                edge='black',
                wick='black',
                volume='in'
            )
        )

        # 清除旧画布
        for child in self.plot_frame.winfo_children():
            child.destroy()

        # 使用 mplfinance 返回 Figure 并嵌入到 Tkinter
        try:
            # 创建自定义样式，强制设置字体
            if chinese_font_prop:
                # 手动创建图形并设置字体
                fig, axlist = mpf.plot(
                    df,
                    type='candle',
                    mav=(5, 10, 20),
                    volume=True,
                    style=market_style,
                    title=f"{symbol.upper()} 真实K线图（通达信风格）",
                    ylabel="价格",
                    ylabel_lower="成交量",
                    figratio=(12, 6),
                    figscale=1.2,
                    returnfig=True,
                    update_width_config=dict(
                        candle_linewidth=1.0,
                        candle_width=0.8,
                    )
                )

                # 手动设置所有文本的字体
                self._set_figure_fonts(fig, chinese_font_prop)

            else:
                # 如果没有中文字体，使用原始方式
                fig, axlist = mpf.plot(
                    df,
                    type='candle',
                    mav=(5, 10, 20),
                    volume=True,
                    style=market_style,
                    title=f"{symbol.upper()} K Line Chart",
                    ylabel="Price",
                    ylabel_lower="Volume",
                    figratio=(12, 6),
                    figscale=1.2,
                    returnfig=True
                )

        except Exception as e:
            messagebox.showerror("绘图错误", f"绘图失败: {e}")
            return

        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas_widget = canvas

    def _set_figure_fonts(self, fig, font_prop):
        """手动设置图形中所有文本的字体"""
        try:
            # 设置标题字体
            if hasattr(fig, '_suptitle') and fig._suptitle is not None:
                fig._suptitle.set_fontproperties(font_prop)

            # 遍历所有轴
            for ax in fig.get_axes():
                # 设置轴标题
                title = ax.get_title()
                if title:
                    ax.set_title(title, fontproperties=font_prop)

                # 设置轴标签
                xlabel = ax.get_xlabel()
                if xlabel:
                    ax.set_xlabel(xlabel, fontproperties=font_prop)

                ylabel = ax.get_ylabel()
                if ylabel:
                    ax.set_ylabel(ylabel, fontproperties=font_prop)

                # 设置刻度标签
                for label in ax.get_xticklabels():
                    label.set_fontproperties(font_prop)

                for label in ax.get_yticklabels():
                    label.set_fontproperties(font_prop)

                # 设置图例（如果有）
                legend = ax.get_legend()
                if legend:
                    for text in legend.get_texts():
                        text.set_fontproperties(font_prop)

            # 强制刷新图形
            fig.canvas.draw_idle()

        except Exception as e:
            print(f"设置字体时出错: {e}")


def main():
    root = tk.Tk()
    app = KlineApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()