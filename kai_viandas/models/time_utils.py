from datetime import datetime

import pytz
from babel.dates import format_date, format_datetime
from odoo import fields


def business_tz(env):
    return env.ref('base.user_admin').sudo().tz or 'UTC'


def business_today(env):
    return datetime.now(pytz.timezone(business_tz(env))).date()


def business_date_domain(env, operator, value, positive='=', negative='!='):
    """Búsqueda booleana de fechas con la referencia operativa compartida."""
    if operator in ('in', 'not in'):
        yes = (True in value) == (operator == 'in')
        no = (False in value) == (operator == 'in')
        if yes == no:
            return [(1, '=', 1 if yes else 0)]
        matched = yes
    elif operator in ('=', '!='):
        matched = bool(value) == (operator == '=')
    else:
        return NotImplemented
    return [('date', positive if matched else negative, business_today(env))]


def day_label(value):
    return format_date(fields.Date.to_date(value), 'EEEE d/MM', locale='es_AR').capitalize() if value else ''


def business_datetime(env, value):
    if not value:
        return ''
    moment = fields.Datetime.to_datetime(value).replace(tzinfo=pytz.UTC)
    return format_datetime(moment, 'dd/MM/yyyy HH:mm', tzinfo=pytz.timezone(business_tz(env)), locale='es_AR')
