from collections import Counter

from odoo import fields, models

from .identity import check_operator
from .operation_labels import pending_label
from .time_utils import business_datetime, day_label


class PreparationCut(models.Model):
    _inherit = 'lafija.preparation.cut'

    def action_print_day_sheet(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access('read')
        return self.current_revision_id.action_print_day_sheet()


class PreparationRevision(models.Model):
    _inherit = 'lafija.preparation.revision'

    def action_print_day_sheet(self):
        check_operator(self.env)
        self.ensure_one()
        self.check_access('read')
        return self.env.ref('kai_viandas.report_day_sheet').report_action(self)


class DaySheetReport(models.AbstractModel):
    _name = 'report.kai_viandas.day_sheet'
    _description = 'Planilla del día para preparación, sin importes'

    def _get_report_values(self, docids, data=None):
        check_operator(self.env)
        revisions = self.env['lafija.preparation.revision'].browse(docids).exists()
        revisions.check_access('read')
        generated_at = business_datetime(self.env, fields.Datetime.now())
        sheets = []
        for revision in revisions:
            lines = revision.line_ids.sorted(lambda line: (
                line.company_name.casefold(), line.customer_company_id.id,
                line.employee_name.casefold(), line.reservation_id.id))
            quantities = Counter(line.product_id.id for line in lines)
            dessert_quantities = Counter(line.dessert_id.id for line in lines if line.dessert_id)
            drink_quantities = Counter(line.drink_id.id for line in lines if line.drink_id)
            # Identidad de producto para agrupar; descripciones de la revisión
            # para conservar exactamente qué elección se tomó para preparar.
            products = lines.product_id.sorted(lambda p: (p.name.casefold(), p.id))
            desserts = lines.dessert_id.sorted(lambda p: (p.name.casefold(), p.id))
            drinks = lines.drink_id.sorted(lambda p: (p.name.casefold(), p.id))
            companies = []
            for company_id in dict.fromkeys(lines.mapped('customer_company_id').ids):
                company_lines = lines.filtered(lambda line: line.customer_company_id.id == company_id)
                companies.append({
                    'name': company_lines[0].company_name,
                    'lines': [{'employee': line.employee_name, 'reference': line.reservation_id.name,
                               'product': line.product_id.display_name, 'choice': line.description,
                               'dessert': line.dessert_description or '',
                               'drink': line.drink_description or '',
                               'quantity': 1} for line in company_lines],
                })
            # La planilla conserva las viandas de la revisión; los pendientes
            # se identifican como estado de atención AL IMPRIMIR, no del corte.
            pending = revision.cut_id.pending_ids.filtered('pending').sorted(lambda r: (
                r.customer_company_id.name.casefold(), r.employee_partner_id.name.casefold(), r.id))
            sheets.append({
                'id': revision.id, 'date': f'{day_label(revision.cut_id.date)}/{revision.cut_id.date.year}',
                'revision': revision.number,
                'current': revision == revision.cut_id.current_revision_id,
                'generated_at': generated_at, 'total': len(lines), 'companies': companies,
                'products': [{'name': p.display_name, 'quantity': quantities[p.id]} for p in products],
                'desserts': [{'name': p.display_name, 'quantity': dessert_quantities[p.id]} for p in desserts],
                'drinks': [{'name': p.display_name, 'quantity': drink_quantities[p.id]} for p in drinks],
                'pending': [{'company': r.customer_company_id.name, 'employee': r.employee_partner_id.name,
                             'reference': r.name,
                             'choice': (r.pending_description or 'Sin cambio de opción') if (r.pending_product_id or r.pending_dessert_id or r.pending_drink_id) else 'Sin cambio de opción',
                             'dessert': r.pending_dessert_description or '',
                             'drink': r.pending_drink_description or '',
                             'type': pending_label(r.current_product_id, r.pending_product_id or r.pending_dessert_id or r.pending_drink_id, r.attention_pending)}
                            for r in pending],
            })
        return {'doc_ids': revisions.ids, 'doc_model': revisions._name, 'sheets': sheets}
