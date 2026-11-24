# kai_portal_set_password (Odoo 17)

Portal: establecer contraseña sin correo.

- Acción **"Establecer contraseña de portal"** en Contactos (menú ⚙ Acción, al final de la lista).
- Si el contacto no tiene usuario, crea un usuario **solo de portal** sin enviar invitación; luego fija la contraseña (sudo) **solo** si el usuario destino es de portal (share) y nunca interno.
- Restringido al grupo **"Puede establecer contraseña de portal"** (los administradores lo heredan).
- Con el parámetro `kai_portal_set_password.disable_portal_invite_email` = `True` (por defecto):
  - "Otorgar acceso al portal" no envía el correo de invitación.
  - No se envían avisos de seguridad ("Contraseña cambiada") a usuarios de portal.

Dependencias: `portal`, `auth_signup`, `contacts`. Versión: 17.0.1.0.0. Licencia: LGPL-3.
