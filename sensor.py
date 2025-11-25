import tkinter as tk
from tkinter import simpledialog, messagebox
from tkinter import ttk
from utils import draw_sensor, calculate_distance, update_sensor_color
from common import sensor_states
from device import devices
from datetime import datetime
from common import active_cycles
from consumption_profiles import get_device_consumption, consumption_profiles
from read import read_sensors as sensors_file
from read import read_devices as devices_file


sensors = []
add_point_enabled = False


def get_sensor_params(sensor_type):
    params = {
        "PIR": {"min": 0.0, "max": 1.0, "step": 1.0, "state": 0.0, "direction": 0, "consumption": None},
        "Temperature": {"min": 18.0, "max": 35.0, "step": 0.5, "state": 18.0, "direction": None, "consumption": None},
        "Switch": {"min": 0, "max": 1, "step": 1, "state": 0, "direction": None, "consumption": None},
        "Smart Meter": {"min": 0.0, "max": 5000.0, "step": 10.0, "state": 0.0, "direction": None, "consumption": 0.0},
        "Weight": {"min": 0.0, "max": 1.0, "step": 1.0, "state": 0.0, "direction": None, "consumption": None},
    }
    return params.get(
        sensor_type,
        {"min": 0.0, "max": 1.0, "step": 1.0, "state": 0.0, "direction": None, "consumption": None},
    )


def add_sensor(canvas, event, load_active):
    global add_point_enabled
    if add_point_enabled:
        return

    x = int(canvas.canvasx(event.x))
    y = int(canvas.canvasy(event.y))

    dialog = SensorDialog(canvas.master, "Add sensor")
    if dialog.result:
        name, type, min_val, max_val, step, state, direction, consumption, associated_device = dialog.result
        sensor = (
            name,
            x,
            y,
            type,
            float(min_val),
            float(max_val),
            float(step),
            float(state),
            direction,
            consumption,
            associated_device,
        )

        # write to the right list according to load_active
        if load_active:
            sensors_file.append(sensor)
        else:
            sensors.append(sensor)

        draw_sensor(canvas, sensor)


def changePIR(canvas, sensor, sensors, new_state=None):
    if len(sensor) != 11:
        print(f"Error: wrong sensor structure {sensor}")
        return None, None, sensors

    name, x, y, type, min_val, max_val, step, state, direction, consumption, associated_device = sensor
    state = float(state)

    if new_state is None:
        new_state = 1 if state == 0 else 0

    updated_sensors = []
    for s in sensors:
        if s == sensor:
            updated_sensors.append(
                (
                    name,
                    x,
                    y,
                    type,
                    min_val,
                    max_val,
                    step,
                    new_state,
                    direction,
                    consumption,
                    associated_device,
                )
            )
        elif s[3] == "PIR":
            updated_sensors.append(
                (s[0], s[1], s[2], s[3], s[4], s[5], s[6], 0, s[8], s[9], s[10])
            )
            update_sensor_color(canvas, s[0], 0, s[4])
        else:
            updated_sensors.append(s)

    update_sensor_color(canvas, name, new_state, float(min_val))
    return name, new_state, updated_sensors


# Stub: qui puoi implementare la lettura reale dal CSV
def get_last_real_temperature(sensor_name: str, n: int):
    """
    Ritorna la temperatura reale filtrata (media degli ultimi n valori).
    Per ora è uno stub che restituisce None.
    """
    return None


def changeTemperature(canvas, sensor, sensors, heating_factor, delta_seconds):
    if len(sensor) != 11:
        print(f"Error: unexpected Temperature structure {sensor}")
        return None, None, sensors

    (
        name,
        x,
        y,
        type,
        min_val,
        max_val,
        step,
        state,
        direction,
        consumption,
        associated_device,
    ) = sensor

    # ---- PARAMETRI BASE ----
    min_val = float(min_val)
    max_val = float(max_val)
    step = float(step)
    current_state = float(state)

    # ---- NUOVO VALORE REALE FILTRATO ----
    # Media ultimi 3 valori dal CSV, se esiste
    real_target = get_last_real_temperature(name, 3)

    # ---- TARGET DELLA SIMULAZIONE ----
    if real_target is not None:
        # Clip ai limiti del sensore
        real_target = max(min_val, min(max_val, real_target))
        target = real_target
    else:
        # segue riscaldamento classico
        target = None

    # ---- MOVIMENTO GRADUALE (0.02°C A MIN SIMULATO) ----
    change_speed = 0.02 * delta_seconds  # proporzionale al tempo simulato

    if target is not None:
        if abs(current_state - target) < change_speed:
            new_state = target
        elif current_state < target:
            new_state = current_state + change_speed
        else:
            new_state = current_state - change_speed
    else:
        # Comportamento normale quando non c'è input reale
        if heating_factor > 0:
            new_state = min(
                current_state + (step * delta_seconds * heating_factor),
                max_val,
            )
        else:
            new_state = max(current_state - (step * delta_seconds), min_val)

    # ---- ARROTONDAMENTO ----
    new_state = round(new_state * 2) / 2.0

    # ---- AGGIORNA ARRAY SENSORI ----
    updated = []
    for s in sensors:
        if s == sensor:
            updated.append(
                (
                    name,
                    x,
                    y,
                    type,
                    min_val,
                    max_val,
                    step,
                    new_state,
                    direction,
                    consumption,
                    associated_device,
                )
            )
        else:
            updated.append(s)

    # ---- AGGIORNA COLORE ----
    update_sensor_color(canvas, name, new_state, min_val)

    return name, new_state, updated


def changeSmartMeter(canvas, sensor, sensors, devices, delta_seconds, current_datetime):
    if len(sensor) < 11:
        print(f"[WARN] Unexpected Smart Meter structure: {sensor}")
        return sensor[0] if sensor else None, 0.0, sensors

    (
        name,
        x,
        y,
        type,
        min_val,
        max_val,
        step,
        state,
        direction,
        _old_consumption,
        associated_device,
    ) = sensor

    new_consumption = 0.0

    if associated_device:
        # searches for the associated device both among runtimes and among those loaded from files
        associated_dev = next((d for d in devices if d[0] == associated_device), None)
        if not associated_dev and devices:
            associated_dev = next((d for d in devices if d[0] == associated_device), None)
        if not associated_dev and devices_file:
            associated_dev = next((d for d in devices_file if d[0] == associated_device), None)

        if associated_dev:
            dev_name, _, _, dev_type, _, dev_state, *_ = associated_dev

            if dev_state == 1:
                if dev_name in active_cycles:
                    new_consumption = get_device_consumption(
                        dev_name, dev_type, current_datetime, active_cycles, dev_state
                    )
                else:
                    prof = consumption_profiles.get(dev_type)
                    if prof:
                        profile = prof["profile"]
                        if profile:
                            first_key = sorted(profile)[0]
                            new_consumption = profile[first_key]
                        else:
                            new_consumption = 0.0
                    else:
                        new_consumption = 0.0
            else:
                new_consumption = 0.0

    # update the sensor array with new consumption
    updated = []
    for s in sensors:
        if s == sensor:
            updated.append(
                (
                    name,
                    x,
                    y,
                    type,
                    min_val,
                    max_val,
                    step,
                    state,
                    direction,
                    new_consumption,
                    associated_device,
                )
            )
        else:
            updated.append(s)

    # update color (green if above minimum threshold)
    update_sensor_color(canvas, name, new_consumption, min_val)

    return name, new_consumption, updated


def ChangeWeight(canvas, sensor, sensors, new_state):
    if len(sensor) != 11:
        print(f"Error: unexpected Weight structure {sensor}")
        return None, None, sensors

    (
        name,
        x,
        y,
        type,
        min_val,
        max_val,
        step,
        state,
        direction,
        consumption,
        associated_device,
    ) = sensor

    updated_sensors = []
    for s in sensors:
        if s == sensor:
            updated_sensor = (
                name,
                x,
                y,
                type,
                min_val,
                max_val,
                step,
                new_state,
                direction,
                consumption,
                associated_device,
            )
            updated_sensors.append(updated_sensor)
        else:
            updated_sensors.append(s)

    update_sensor_color(canvas, name, new_state, float(min_val))
    return name, new_state, updated_sensors


class SensorDialog(simpledialog.Dialog):
    def body(self, master):
        tk.Label(master, text="Sensor name:").grid(row=0)
        tk.Label(master, text="Sensor type:").grid(row=1)

        self.sensor_name = tk.Entry(master)
        self.sensor_name.grid(row=0, column=1)

        self.sensor_type = ttk.Combobox(
            master,
            values=["PIR", "Temperature", "Switch", "Smart Meter", "Weight"],
        )
        self.sensor_type.grid(row=1, column=1)
        self.sensor_type.current(0)

        self.direction_label = tk.Label(master, text="Direction (degrees):")
        self.direction_entry = tk.Entry(master)

        self.associated_device_label = tk.Label(master, text="Associated device:")

        # Merge runtime + devices loaded from files (without duplicates)
        devices_names_runtime = [d[0] for d in devices] if devices else []
        devices_names_file = [d[0] for d in devices_file] if devices_file else []
        devices_names = sorted(set(devices_names_runtime + devices_names_file))

        self.associated_device_combobox = ttk.Combobox(master, values=devices_names)

        self.sensor_type.bind("<<ComboboxSelected>>", self.on_sensor_type_selected)

        return self.sensor_name

    # Show 'direction' for PIR or 'associated device' for Smart Meter only.
    def on_sensor_type_selected(self, event):
        type = self.sensor_type.get()

        if type == "PIR":
            self.direction_label.grid(row=2, column=0)
            self.direction_entry.grid(row=2, column=1)

            self.associated_device_label.grid_remove()
            self.associated_device_combobox.grid_remove()

        elif type == "Smart Meter":
            self.direction_label.grid_remove()
            self.direction_entry.grid_remove()

            self.associated_device_label.grid(row=2, column=0)
            self.associated_device_combobox.grid(row=2, column=1)

            if self.associated_device_combobox["values"]:
                self.associated_device_combobox.current(0)

        else:
            self.direction_label.grid_remove()
            self.direction_entry.grid_remove()
            self.associated_device_label.grid_remove()
            self.associated_device_combobox.grid_remove()

    # Check for empty/duplicate name; require direction (PIR) or device (Smart Meter).
    def validate(self):
        name = self.sensor_name.get().strip()
        if not name:
            messagebox.showwarning("Input not valid", "Sensor name cannot be empty.")
            return False

        for s in sensors + list(sensors_file):
            if name == s[0]:
                messagebox.showwarning("Input not valid", "Sensor name already exists.")
                return False

        if self.sensor_type.get() == "PIR" and not self.direction_entry.get().strip():
            messagebox.showwarning("Input not valid", "Pir sensor direction cannot be empty.")
            return False

        if self.sensor_type.get() == "Smart Meter" and not self.associated_device_combobox.get():
            messagebox.showwarning(
                "Input not valid",
                "Select a device to associate with the Smart Meter.",
            )
            return False

        return True

    def apply(self):
        name = self.sensor_name.get()
        type = self.sensor_type.get()
        params = get_sensor_params(type)

        if type == "PIR":
            direction = float(self.direction_entry.get())
            params["direction"] = direction

        associated_device = (
            self.associated_device_combobox.get()
            if type == "Smart Meter"
            else None
        )

        self.result = (
            name,
            type,
            params["min"],
            params["max"],
            params["step"],
            params["state"],
            params.get("direction", None),
            params["consumption"],
            associated_device,
        )