# graph.py
from __future__ import annotations

import os, csv, tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime, date
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.ticker import MaxNLocator, FormatStrFormatter
import pandas as pd

from sensor import sensors
from read import read_sensors
import smartmeter 
import json
import dhtlogger

plt.rcParams.update({
    "axes.titlesize": 16,
    "axes.labelsize": 14,
    "xtick.labelsize": 10,
    "ytick.labelsize": 12,
    "legend.fontsize": 12
})


REAL_ID_BY_SENSOR = {}

def _load_sensor_map(path="sensor_map.json") -> dict:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
    except: pass
    return {}

def _get_binding_dht_gpio_for_sensor(sensor_name: str) -> int | None:
    mp = _load_sensor_map()
    v = mp.get(sensor_name)
    if isinstance(v, dict) and v.get("by") == "dht":
        try:
            return int(v.get("gpio"))
        except Exception:
            return None
    return None

def _load_sensor_map(path="sensor_map.json") -> dict:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _dual_plot_temperature(ax, sensor: str, sensor_data: dict):
    # --- simulated
    time_list = sensor_data.get('time', [])
    y_sim = sensor_data.get('state', []) 
    df_sim = _build_dataframe(time_list, y_sim) if (time_list and y_sim) else pd.DataFrame()

    # --- real
    df_real = dhtlogger.load_temp_by_label_any_csv(sensor, logs_dir="logs")

    if df_sim.empty and df_real.empty:
        ax.text(0.5, 0.5, "Nessun dato (sim/reale) per Temperature", ha="center", va="center", transform=ax.transAxes)
        return None, "Temperature (°C)"

    ref_day = (df_sim.index[0].date() if not df_sim.empty else date(1900,1,1))
    if not df_real.empty:
        df_real = df_real.copy()
        df_real.index = [datetime.combine(ref_day, t.time()) for t in df_real.index]

    if not df_sim.empty:
        ax.plot(df_sim.index, df_sim["value"], linestyle='-', linewidth=1.5, marker='o', markersize=2, label=f"{sensor} (sim)")
    if not df_real.empty:
        ax.plot(df_real.index, df_real["value"], linestyle='--', linewidth=1.5, label=f"{sensor} (reale)")

    ax.yaxis.set_major_locator(MaxNLocator(8))
    ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
    return (df_sim if not df_sim.empty else df_real), "Temperature (°C)"


def _get_binding_ip_for_sensor(sensor_name: str) -> str | None:
    mp = _load_sensor_map()
    v = mp.get(sensor_name)
    if isinstance(v, dict) and v.get("by") == "ip" and isinstance(v.get("value"), str):
        ip = v["value"].strip()
        return ip if ip else None
    return None


# ----------------- utilità base -----------------
def _parse_datetime(time_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    return datetime.strptime(time_str, "%H:%M").replace(year=1900, month=1, day=1)

def _align_len(lst, target_len, fill=None):
    if lst is None:
        return [fill] * target_len
    out = list(lst)
    if len(out) < target_len:
        out.extend([fill] * (target_len - len(out)))
    elif len(out) > target_len:
        out = out[:target_len]
    return out

def _build_dataframe(time_list_str, values_list):
    time_list = [_parse_datetime(t) for t in time_list_str]
    vals = pd.to_numeric(pd.Series(values_list), errors="coerce")
    df = pd.DataFrame({"timestamp": time_list, "value": vals})
    df = df.dropna(subset=["value"])
    if df.empty:
        return df
    df.sort_values("timestamp", inplace=True)
    df = df.drop_duplicates(subset="timestamp", keep="last")
    df.set_index("timestamp", inplace=True)
    return df.resample("1min").ffill()

def _sensor_type(name: str, sensor_states: dict):
    t = sensor_states.get(name, {}).get("type")
    if t:
        return t
    for s in sensors:
        if s[0] == name:
            return s[3]
    for s in read_sensors:
        if s[0] == name:
            return s[3]
    if "consumption" in sensor_states.get(name, {}):
        return "Smart Meter"
    return None

def _latest_interactions_csv():
    logs_root = "logs"
    if not os.path.isdir(logs_root):
        return None
    candidates = []
    for name in os.listdir(logs_root):
        folder = os.path.join(logs_root, name)
        csv_path = os.path.join(folder, "interactions.csv")
        if os.path.isdir(folder) and os.path.isfile(csv_path):
            candidates.append((os.path.getmtime(csv_path), csv_path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]

def _load_consumption_from_interactions(sensor_name: str) -> dict:
    """Solo dati simulati (niente fallback al reale: il reale lo carichiamo nel dual-plot)."""
    path = _latest_interactions_csv()
    if not path:
        return {}
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("event_type") == "sensor" and row.get("name") == sensor_name:
                    ts = row.get("timestamp_sim", "")
                    val = row.get("value", "")
                    try:
                        out[ts] = float(val)
                    except Exception:
                        continue
    except Exception:
        return {}
    return out


def _normalize_index_to_date(df: pd.DataFrame, target_day: date) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df.index = [datetime.combine(target_day, t.time()) for t in df.index]
    return df

def _dual_plot_smart(ax, sensor: str, sensor_data: dict, sensor_states: dict):
    #SIMULATED
    time_list = sensor_data.get('time', [])
    consumption_list = sensor_data.get('consumption')
    if not consumption_list:
        m = _load_consumption_from_interactions(sensor)
        if m:
            keys = list(m.keys())
            mapped = []
            for t in time_list:
                key = None
                if len(t) == 5:
                    suffix = f" {t}"
                    for k in keys:
                        if k.endswith(suffix):
                            key = k
                            break
                else:
                    if t in m:
                        key = t
                mapped.append(m[key] if key is not None else None)
            consumption_list = mapped

    y_series_sim = _align_len(consumption_list, len(time_list), fill=None) if consumption_list else []
    df_sim = _build_dataframe(time_list, y_series_sim) if y_series_sim else pd.DataFrame()

    #REAL
    df_real = pd.DataFrame()
    ip_binding = _get_binding_ip_for_sensor(sensor)
    if ip_binding:
        df_real = smartmeter.load_power_by_ip_any_csv(ip_binding, logs_dir="logs")


    if df_sim.empty and df_real.empty:
        ax.text(0.5, 0.5, "Nessun dato (né simulato né reale) per Smart Meter", ha="center", va="center", transform=ax.transAxes)
        return None, "Power (W)"

    ref_day = (df_sim.index[0].date() if not df_sim.empty else date(1900, 1, 1))
    df_real = _normalize_index_to_date(df_real, ref_day)

    # PLOT
    if not df_sim.empty:
        ax.plot(df_sim.index, df_sim["value"], linestyle='-', linewidth=1.5, marker='o', markersize=2, label=f"{sensor} (sim)")
    if not df_real.empty:
        ax.plot(df_real.index, df_real["value"], linestyle='--', linewidth=1.5, label=f"{sensor} (reale)")

    ax.yaxis.set_major_locator(MaxNLocator(8))
    ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))

    df_for_date = df_sim if not df_sim.empty else df_real
    return df_for_date, "Power (W)"

#UI
def show_graphs(canvas, sensor_states):
    def generate_graph(sensor, sensor_data, frame):
        fig, ax = plt.subplots(figsize=(12, 6))

        time_list = sensor_data.get('time', [])
        state_list = sensor_data.get('state', [])
        sensor_type = _sensor_type(sensor, sensor_states)

        if sensor_type == "Temperature":
            df_for_date, y_label = _dual_plot_temperature(ax, sensor, sensor_data)
        elif sensor_type == "Smart Meter":
            df_for_date, y_label = _dual_plot_smart(ax, sensor, sensor_data, sensor_states)
        try:
            date_str = df_for_date.index[0].date() if df_for_date is not None else ""
        except Exception:
            date_str = ""
        ax.set_title(f"{sensor} - {date_str}")
        ax.set_xlabel("Time")
        ax.set_ylabel(y_label)

        ax.legend()
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        fig.tight_layout()

        canvas_plot = FigureCanvasTkAgg(fig, master=frame)
        toolbar = NavigationToolbar2Tk(canvas_plot, frame)
        toolbar.update()
        toolbar.pack(side=tk.TOP, fill=tk.X)
        canvas_plot.draw()
        canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)
        return

        # --- branch generico ---
        y_series = state_list
        if sensor_type == "Temperature":
            y_label = "Temperature (°C)"
        elif sensor_type in ("PIR", "Switch"):
            y_label = "State"
        else:
            y_label = "Value"

        df = _build_dataframe(time_list, y_series) if y_series else pd.DataFrame()
        if df.empty:
            if y_series:
                ax.text(0.5, 0.5, "No valid data to plot", ha="center", va="center", transform=ax.transAxes)
        else:
            unique_vals = set(df["value"].dropna().unique().tolist())
            is_binary = unique_vals.issubset({0.0, 1.0})
            if is_binary and sensor_type not in ("Smart Meter", "Temperature"):
                ax.plot(df.index, df["value"], drawstyle='steps-post', marker='o', linestyle='-', label=sensor)
                ax.set_ylim(-0.1, 1.1)
                ax.set_yticks([0, 1])
            else:
                ax.plot(df.index, df["value"], linestyle='-', linewidth=1.5, marker='o', markersize=2, label=sensor)

        try:
            date_str = df.index[0].date() if not df.empty else ""
        except Exception:
            date_str = ""
        ax.set_title(f"{sensor} - {date_str}")
        ax.set_xlabel("Time")
        ax.set_ylabel(y_label)

        ax.legend()
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.yaxis.set_major_locator(MaxNLocator(8))
        ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        fig.tight_layout()

        canvas_plot = FigureCanvasTkAgg(fig, master=frame)
        toolbar = NavigationToolbar2Tk(canvas_plot, frame)
        toolbar.update()
        toolbar.pack(side=tk.TOP, fill=tk.X)
        canvas_plot.draw()
        canvas_plot.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)

    def save_selected_logs():
        selected = [s for s, state in select_sensors.items() if state.get()]
        if not selected:
            messagebox.showwarning("Warning", "Select at least one sensor to generate the graph.")
            return

        graph_window = tk.Toplevel()
        graph_window.title("Graphs from sensors")

        container = ttk.Frame(graph_window)
        sc_canvas = tk.Canvas(container)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=sc_canvas.yview)
        scrollable_frame = ttk.Frame(sc_canvas)

        scrollable_frame.bind("<Configure>", lambda e: sc_canvas.configure(scrollregion=sc_canvas.bbox("all")))
        sc_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        sc_canvas.configure(yscrollcommand=scrollbar.set)

        container.pack(fill="both", expand=True)
        sc_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for sensor in selected:
            frame = ttk.Frame(scrollable_frame)
            frame.pack(fill="both", pady=10)
            generate_graph(sensor, sensor_states[sensor], frame)

    selection_window = tk.Toplevel()
    selection_window.title("Select sensors")

    tk.Label(selection_window, text="Select the sensors for which to generate the graph:").pack(pady=10)
    select_sensors = {s: tk.BooleanVar() for s in sensor_states.keys()}

    select_all_var = tk.BooleanVar(value=False)
    def on_toggle_select_all():
        val = bool(select_all_var.get())
        for var in select_sensors.values():
            var.set(val)

    tk.Checkbutton(selection_window, text="Select all", variable=select_all_var, command=on_toggle_select_all, fg="blue").pack(anchor="w", pady=(0, 5))

    for sensor, state in select_sensors.items():
        tk.Checkbutton(selection_window, text=sensor, variable=state).pack(anchor="w")

    tk.Button(selection_window, text="Generate Graphs", command=save_selected_logs).pack(pady=10)


def show_graphs_auto(sensor_states, selected_keys, target_frame):
    def generate_graph(sensor, sensor_data, frame):
        fig, ax = plt.subplots(figsize=(12, 6))

        time_list = sensor_data.get('time', [])
        state_list = sensor_data.get('state', [])
        sensor_type = _sensor_type(sensor, sensor_states)

        if sensor_type == "Smart Meter":
            df_for_date, y_label = _dual_plot_smart(ax, sensor, sensor_data, sensor_states)
            try:
                date_str = df_for_date.index[0].date() if df_for_date is not None else ""
            except Exception:
                date_str = ""
            ax.set_title(f"{sensor} - {date_str}")
            ax.set_xlabel("Time")
            ax.set_ylabel(y_label)
        else:
            y_series = state_list
            if sensor_type == "Temperature":
                y_label = "Temperature (°C)"
            elif sensor_type in ("PIR", "Switch"):
                y_label = "State"
            else:
                y_label = "Value"

        df = _build_dataframe(time_list, y_series) if y_series else pd.DataFrame()
        if df.empty:
            if y_series:
                ax.text(0.5, 0.5, "No valid data to plot", ha="center", va="center", transform=ax.transAxes)
        else:
            unique_vals = set(df["value"].dropna().unique().tolist())
            is_binary = unique_vals.issubset({0.0, 1.0})
            if is_binary and sensor_type not in ("Smart Meter", "Temperature"):
                ax.plot(df.index, df["value"], drawstyle='steps-post', marker='o', linestyle='-', label=sensor)
                ax.set_ylim(-0.1, 1.1)
                ax.set_yticks([0, 1])
            else:
                ax.plot(df.index, df["value"], linestyle='-', linewidth=1.5, marker='o', markersize=2, label=sensor)

        ax.set_title(f"Sensor trend: {sensor}")
        ax.set_xlabel("Time")
        ax.set_ylabel(y_label)

        ax.legend()
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.yaxis.set_major_locator(MaxNLocator(8))
        ax.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        fig.tight_layout()

        canvas_plot = FigureCanvasTkAgg(fig, master=frame)
        toolbar = NavigationToolbar2Tk(canvas_plot, frame)
        toolbar.update()
        toolbar.pack(side=tk.TOP, fill=tk.X)
        canvas_plot.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        canvas_plot.draw()
        plt.close(fig)

    for w in target_frame.winfo_children():
        w.destroy()

    container = ttk.Frame(target_frame)
    container.pack(fill="both", expand=True)

    for key in selected_keys:
        if key not in sensor_states:
            continue
        card = ttk.Frame(container)
        card.pack(fill="x", pady=10)
        generate_graph(key, sensor_states[key], card)

def get_last_real_temperature(label, n=3):
    """
    Legge la media degli ultimi N valori reali dal sensore DHT <label>.
    Ritorna None se non ci sono valori validi.
    """
    file = f"logs/dht_{label}.csv"
    if not os.path.exists(file):
        return None

    try:
        df = pd.read_csv(file)
    except:
        return None

    if "temp" not in df.columns:
        return None

    # Rimuove valori vuoti o non numerici
    df = df[pd.to_numeric(df["temp"], errors="coerce").notnull()]

    if len(df) == 0:
        return None

    # Prende ultimi N valori
    last_values = df["temp"].astype(float).tail(n)

    return round(last_values.mean(), 2)