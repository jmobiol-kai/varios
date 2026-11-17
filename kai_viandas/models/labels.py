from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .identity import check_operator
from .reservation import check_operation, operation_context


class PreparationRevision(models.Model):
    _inherit = "lafija.preparation.revision"

    print_ids = fields.One2many("lafija.label.print", "revision_id", "Archivos generados", readonly=True)

    def action_print_labels(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access("read")
        if not self.line_ids:
            raise ValidationError(_("Esta revisión no tiene viandas para etiquetar."))
        batch = self.env["lafija.label.print"].sudo().with_context(**operation_context()).create({
            "revision_id": self.id, "actor_id": self.env.uid, "generated_at": fields.Datetime.now(),
        })
        # Se conserva el archivo exacto que se entregó al operador, además de la revisión.
        pdf, output = self.env["ir.actions.report"].with_context(force_report_rendering=True)._render_qweb_pdf(
            "kai_viandas.report_labels", batch.ids,
        )
        if output != "pdf" or not pdf.startswith(b"%PDF"):
            raise ValidationError(_("No se pudo generar el archivo de etiquetas."))
        attachment = self.env["ir.attachment"].sudo().create({
            "name": f"{batch.name}.pdf", "raw": pdf, "mimetype": "application/pdf",
            "res_model": batch._name, "res_id": batch.id, "public": False,
        })
        batch.with_context(**operation_context()).write({"attachment_id": attachment.id})
        return {"type": "ir.actions.act_window", "res_model": batch._name, "res_id": batch.id,
                "view_mode": "form", "target": "current"}


class LabelPrint(models.Model):
    _name = "lafija.label.print"
    _description = "Archivo de etiquetas generado"
    _order = "generated_at desc, id desc"

    name = fields.Char("Archivo", compute="_compute_name", store=True)
    revision_id = fields.Many2one("lafija.preparation.revision", "Revisión", required=True, ondelete="restrict")
    actor_id = fields.Many2one("res.users", "Generado por", required=True)
    generated_at = fields.Datetime("Generado el", required=True)
    attachment_id = fields.Many2one("ir.attachment", "PDF conservado", readonly=True, ondelete="restrict")
    handling_ids = fields.One2many("lafija.label.handling", "new_print_id", "Sustituciones coordinadas", readonly=True)

    @api.depends("revision_id.name")
    def _compute_name(self):
        for batch in self:
            batch.name = f"{batch.revision_id.name} · archivo {batch.id}"

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        check_operation(self.env)
        if set(values) != {"attachment_id"} or any(self.mapped("attachment_id")):
            raise AccessError(_("El archivo generado y su procedencia se conservan."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("El registro de impresión no se elimina."))

    def action_download(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access("read")
        if not self.attachment_id:
            raise ValidationError(_("No hay un archivo generado para esta impresión."))
        return {"type": "ir.actions.act_url", "url": f"/web/content/{self.attachment_id.id}?download=true", "target": "self"}

    def action_register_replacement(self):
        check_operator(self.env)
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("Registrar sustitución de etiquetas"), "res_model": "lafija.label.replacement",
                "view_mode": "form", "target": "new", "context": {"default_new_print_id": self.id}}


class LabelHandling(models.Model):
    _name = "lafija.label.handling"
    _description = "Constancia de coordinación de etiquetas"

    new_print_id = fields.Many2one("lafija.label.print", "Archivo sustituto", required=True, ondelete="restrict")
    old_print_id = fields.Many2one("lafija.label.print", "Archivo anterior", required=True, ondelete="restrict")
    actor_id = fields.Many2one("res.users", "Coordinó", required=True)
    occurred_at = fields.Datetime("Cuándo", required=True)
    note = fields.Text("Qué se coordinó", required=True)

    @api.model_create_multi
    def create(self, values_list):
        check_operation(self.env)
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("Registrá otra constancia si necesitás corregir la coordinación."))

    def unlink(self):
        raise AccessError(_("La constancia de sustitución se conserva."))


class LabelReplacement(models.TransientModel):
    _name = "lafija.label.replacement"
    _description = "Registrar sustitución de etiquetas"

    new_print_id = fields.Many2one("lafija.label.print", "Archivo sustituto", required=True, readonly=True)
    old_print_id = fields.Many2one("lafija.label.print", "Archivo anterior", required=True)
    cut_id = fields.Many2one(related="new_print_id.revision_id.cut_id")
    new_generated_at = fields.Datetime(related="new_print_id.generated_at")
    note = fields.Text("Qué reemplazo físico de etiquetas se coordinó", required=True)

    def action_apply(self):
        check_operator(self.env)
        self.ensure_one()
        if (self.old_print_id.revision_id.cut_id != self.new_print_id.revision_id.cut_id
                or (self.old_print_id.generated_at, self.old_print_id.id)
                >= (self.new_print_id.generated_at, self.new_print_id.id)):
            raise ValidationError(_("Elegí un archivo anterior de la misma lista de preparación."))
        if not (self.note or "").strip():
            raise ValidationError(_("Describí la coordinación realizada."))
        self.env["lafija.label.handling"].sudo().with_context(**operation_context()).create({
            "new_print_id": self.new_print_id.id, "old_print_id": self.old_print_id.id,
            "actor_id": self.env.uid, "occurred_at": fields.Datetime.now(), "note": self.note.strip(),
        })
        return {"type": "ir.actions.act_window_close"}


class LabelReport(models.AbstractModel):
    _name = "report.kai_viandas.labels"
    _description = "Contenido de las etiquetas de viandas"

    def _get_report_values(self, docids, data=None):
        check_operator(self.env)
        batches = self.env["lafija.label.print"].browse(docids)
        batches.check_access("read")
        return {"doc_ids": batches.ids, "doc_model": batches._name, "docs": batches}


class Reports(models.Model):
    _inherit = "ir.actions.report"

    def _get_layout(self):
        if len(self) == 1 and self.report_name in ("kai_viandas.labels", "kai_viandas.day_sheet", "kai_viandas.quotation_annex"):
            return self.env.ref("kai_viandas.label_minimal_layout")
        return super()._get_layout()
