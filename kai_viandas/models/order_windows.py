"""Horarios de pedido de La Fija (zona del usuario administrador de Odoo)."""
from datetime import datetime, time, timedelta

import pytz
from odoo import fields

from .time_utils import business_tz

DEFAULT_DAILY_CUTOFF = "10:30"
DEFAULT_WEEKLY_CLOSE_WEEKDAY = 5  # sábado (lunes = 0)
DEFAULT_WEEKLY_CLOSE_TIME = "14:00"
PARAM_DAILY = "kai_viandas.daily_cutoff"
PARAM_WEEKDAY = "kai_viandas.weekly_close_weekday"
PARAM_WEEKLY_TIME = "kai_viandas.weekly_close_time"
WEEKDAYS_ES = {
    0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
    4: "viernes", 5: "sábado", 6: "domingo",
}


def _parse_hhmm(raw, default):
    text = (raw or "").strip() or default
    try:
        hour_s, minute_s = text.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (TypeError, ValueError):
        hour_s, minute_s = default.split(":")
        return int(hour_s), int(minute_s)


def _format_hhmm(hour, minute):
    return f"{hour:02d}:{minute:02d}"


def daily_cutoff_hm(env):
    return _parse_hhmm(env["ir.config_parameter"].sudo().get_param(PARAM_DAILY), DEFAULT_DAILY_CUTOFF)


def weekly_close_hm(env):
    return _parse_hhmm(
        env["ir.config_parameter"].sudo().get_param(PARAM_WEEKLY_TIME), DEFAULT_WEEKLY_CLOSE_TIME)


def weekly_close_weekday(env):
    raw = env["ir.config_parameter"].sudo().get_param(PARAM_WEEKDAY)
    # get_param devuelve False si no está definido; int(False) es 0 (lunes).
    if raw in (None, False, ""):
        return DEFAULT_WEEKLY_CLOSE_WEEKDAY
    try:
        value = int(raw)
        if 0 <= value <= 6:
            return value
    except (TypeError, ValueError):
        pass
    return DEFAULT_WEEKLY_CLOSE_WEEKDAY


def daily_cutoff_label(env):
    return _format_hhmm(*daily_cutoff_hm(env))


def weekly_close_label(env):
    return _format_hhmm(*weekly_close_hm(env))


def weekly_close_day_name(env):
    return WEEKDAYS_ES[weekly_close_weekday(env)]


def _local_now(env, moment=None):
    zone = pytz.timezone(business_tz(env))
    if moment is None:
        moment = fields.Datetime.now()
    if moment.tzinfo is None:
        moment = pytz.UTC.localize(moment)
    return moment.astimezone(zone)


def local_datetime(env, day, hour, minute, second=0):
    zone = pytz.timezone(business_tz(env))
    local = zone.localize(datetime.combine(day, time(hour, minute, second)))
    return local.astimezone(pytz.UTC).replace(tzinfo=None)


def daily_cutoff_datetime(env, day):
    hour, minute = daily_cutoff_hm(env)
    return local_datetime(env, day, hour, minute)


def weekly_close_datetime(env, week_start):
    """Cierre anticipado de la semana que empieza en week_start: el día configurado de la semana anterior."""
    weekday = weekly_close_weekday(env)
    hour, minute = weekly_close_hm(env)
    # week_start es lunes de la semana del menú; el cierre es en la semana previa.
    close_day = week_start - timedelta(days=7 - weekday)
    return local_datetime(env, close_day, hour, minute)


def advance_week_start(week_start):
    return week_start - timedelta(days=7)


def window_state(env, menu_date, moment=None):
    """Estado de la ventana del empleado para un día de menú.

    - open: puede pedir, cambiar o cancelar
    - daily_closed: pasó el corte del día del menú (por defecto 10:30)
    - weekly_closed: entre el cierre anticipado (sábado 14:00) y el lunes de esa semana
    - future_week_closed: todavía no empezó la semana de carga anticipada
    """
    now = fields.Datetime.to_datetime(moment or fields.Datetime.now())
    week_start = menu_date - timedelta(days=menu_date.weekday())
    daily_close = daily_cutoff_datetime(env, menu_date)
    if now >= daily_close:
        return "daily_closed"
    local_date = _local_now(env, now).date()
    adv_start = advance_week_start(week_start)
    adv_close = weekly_close_datetime(env, week_start)
    if local_date >= week_start:
        return "open"
    if adv_start <= local_date and now < adv_close:
        return "open"
    if now >= adv_close and local_date < week_start:
        return "weekly_closed"
    return "future_week_closed"


def window_open(env, menu_date, moment=None):
    return window_state(env, menu_date, moment) == "open"


def window_message(env, menu_date, moment=None):
    state = window_state(env, menu_date, moment)
    daily = daily_cutoff_label(env)
    weekly = weekly_close_label(env)
    day_name = weekly_close_day_name(env)
    if state == "daily_closed":
        return (f"El horario para pedir o cambiar este día cerró a las {daily}, "
                "hora de La Fija. Si hace falta una corrección, escribile a La Fija.")
    if state == "weekly_closed":
        return (f"La carga anticipada de pedidos para esa semana cerró el {day_name} a las {weekly}, "
                f"hora de La Fija. Podés hacer cambios, agregados o cancelaciones a partir del lunes, "
                f"siempre hasta las {daily} del día del menú.")
    if state == "future_week_closed":
        return (f"Los pedidos de esa semana se cargan durante la semana anterior, "
                f"hasta el {day_name} a las {weekly}, hora de La Fija.")
    return ""
