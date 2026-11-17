from odoo import api, fields, models

from .identity import check_operator
from .order_windows import (
    DEFAULT_DAILY_CUTOFF, DEFAULT_WEEKLY_CLOSE_TIME, DEFAULT_WEEKLY_CLOSE_WEEKDAY,
    PARAM_DAILY, PARAM_WEEKDAY, PARAM_WEEKLY_TIME,
    weekly_close_hm, weekly_close_weekday,
)


class OrderWindowSettings(models.TransientModel):
    _name = "lafija.order.window.settings"
    _description = "Horarios de pedido de La Fija"

    lf_daily_cutoff = fields.Char(
        "Corte diario del menú",
        help="Hora de La Fija (HH:MM). Hasta este horario del día del menú, el empleado puede pedir, "
             "cambiar o agregar. Después ya no puede modificar ese día en el portal.",
    )
    lf_weekly_close_weekday = fields.Selection(
        [
            ("0", "Lunes"), ("1", "Martes"), ("2", "Miércoles"), ("3", "Jueves"),
            ("4", "Viernes"), ("5", "Sábado"), ("6", "Domingo"),
        ],
        string="Cierre de la carga anticipada",
        help="Día de la semana anterior a la del menú en que cierra la carga anticipada.",
    )
    lf_weekly_close_time = fields.Char(
        "Hora de cierre anticipado",
        help="Hora de La Fija (HH:MM) del cierre anticipado. Por defecto, sábado 14:00 para la semana siguiente.",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        params = self.env["ir.config_parameter"].sudo()
        hour, minute = weekly_close_hm(self.env)
        values.update({
            "lf_daily_cutoff": params.get_param(PARAM_DAILY, DEFAULT_DAILY_CUTOFF) or DEFAULT_DAILY_CUTOFF,
            "lf_weekly_close_weekday": str(weekly_close_weekday(self.env)),
            "lf_weekly_close_time": params.get_param(PARAM_WEEKLY_TIME, DEFAULT_WEEKLY_CLOSE_TIME) or f"{hour:02d}:{minute:02d}",
        })
        return values

    def action_save(self):
        check_operator(self.env)
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(PARAM_DAILY, (self.lf_daily_cutoff or DEFAULT_DAILY_CUTOFF).strip())
        params.set_param(PARAM_WEEKDAY, self.lf_weekly_close_weekday or str(DEFAULT_WEEKLY_CLOSE_WEEKDAY))
        params.set_param(PARAM_WEEKLY_TIME, (self.lf_weekly_close_time or DEFAULT_WEEKLY_CLOSE_TIME).strip())
        return {
            "type": "ir.actions.client",
            "tag": "lf_operation_feedback",
            "params": {"message": "Horarios de pedido actualizados.", "type": "success", "close": True},
        }
