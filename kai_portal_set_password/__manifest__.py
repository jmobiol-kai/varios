{
    'name': 'Portal: establecer contraseña sin correo',
    'version': '17.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Permite a un grupo de usuarios crear usuarios de portal y fijarles la contraseña desde Contactos, sin enviar correos.',
    'description': """
Portal: establecer contraseña sin correo
========================================

* Acción "Establecer contraseña de portal" en Contactos (menú Acción del contacto).
* Si el contacto no tiene usuario, crea uno SOLO de portal (sin correo de invitación).
* Fija la contraseña con sudo únicamente si el usuario destino es de portal (share) y
  nunca interno. En cualquier otro caso rechaza.
* Solo la pueden usar los miembros del grupo "Puede establecer contraseña de portal"
  (los administradores lo heredan).
* Opcional: el asistente estándar "Otorgar acceso al portal" deja de enviar correos
  mientras el parámetro ``kai_portal_set_password.disable_portal_invite_email`` sea verdadero.
  Con el mismo parámetro tampoco se envían avisos de seguridad ("Contraseña cambiada") a usuarios de portal.
""",
    'author': 'Juan Manuel Obiol',
    'depends': ['portal', 'auth_signup', 'contacts'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'wizard/portal_password_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
