# Renombrar msb_lafija a kai_viandas

Este directorio guarda el procedimiento para cambiar el nombre tecnico del modulo sin perder datos. Los modelos de negocio (`lafija.reservation`, campos `lf_*`, tablas `lafija_*`) no se renombran.

## Orden (imprescindible)

1. Copia de seguridad:
   - En produccion (base `lafija`): dump completo (`pg_dump -Fc`) y un tar del codigo de `msb_lafija` y de `msb_lafija_quick_checkout`.
   - En test: alcanza un tar del codigo.
2. Dejar `kai_viandas/` en un directorio de `addons_path` (en este servidor, `.../addons/dev-addons/`).
3. Parchear `msb_lafija_quick_checkout` (sigue con ese nombre, pero depende de `kai_viandas`):
   `bash patch_msb_lafija_quick_checkout.sh /ruta/msb_lafija_quick_checkout`
4. Ejecutar `migrate_rename.sql` sobre la base (o `migrate_rename.sh`).
5. Quitar o renombrar la carpeta `msb_lafija` del addons_path (si quedan las dos, Odoo veria dos modulos con los mismos modelos). Conservar el tar.
6. Actualizar: `odoo -d <base> -u kai_viandas --stop-after-init`
7. Reiniciar el servicio Odoo.

No usar `LIKE '%msb_lafija%'` sobre `ir_module_module.name`: eso tambien coincidiria con `msb_lafija_quick_checkout`.

## Salto de version en produccion

Produccion esta hoy en `msb_lafija` 19.0.1.11.0. `kai_viandas` 19.0.2.0.0 incluye las migraciones intermedias 19.0.1.12.0, 1.14.0, 1.14.1, 1.14.2, 1.15.0, 1.17.6 y 1.17.8. Al hacer `-u` se aplican solas.

- 1.17.6 pasa el presupuesto a un paso explicito (puede desvincular o cancelar borradores de pedidos diarios no elaborados).
- 1.17.8 acumula OF en borrador por plato y dia y aplica elecciones pendientes (sin la exclusion de prueba V-000086).
