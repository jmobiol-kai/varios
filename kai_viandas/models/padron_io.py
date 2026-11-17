"""CSV de entrada y archivo efímero. Nunca adjuntar credenciales al chatter."""
import csv
import hashlib
import io
import os
from pathlib import Path
import re
import time
import unicodedata
import uuid

from odoo.tools import config
from odoo.exceptions import ValidationError


# Límites fijos: cada envío conserva su validación, atomicidad y CSV propios.
MAX_ROWS = 200
MAX_INPUT_BYTES = 512 * 1024
CREDENTIAL_SECONDS = 15 * 60
LOGIN_RE = re.compile(r'^[A-Za-z][A-Za-z0-9._-]{0,127}$')


def normal_name(value):
    return ' '.join((value or '').split()).casefold()


def identifier(value):
    plain = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return '.'.join(re.findall(r'[a-z0-9]+', plain))


def safe_login(value):
    # CSV conserva literalmente usuario/contraseña: no añadirles comillas de
    # fórmula ni prefijos ocultos. El identificador nuevo debe ser texto seguro.
    return bool(LOGIN_RE.fullmatch(value)) and value.casefold() not in ('true', 'false')


def parse_padron(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_INPUT_BYTES:
        raise ValidationError('El padrón supera 512 KiB. Separalo en archivos más pequeños.')
    try:
        text = raw.decode('utf-8-sig')
        if '\x00' in text:
            raise ValueError()
        reader = csv.reader(io.StringIO(text, newline=''), delimiter=';', strict=True)
        header = next(reader)
        if (len(set(header)) != len(header) or 'nombre' not in header
                or not set(header) <= {'nombre', 'usuario', 'legajo'}):
            raise ValueError()
        result = []
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise ValidationError(f'Fila {reader.line_num}: la cantidad de columnas no coincide con el encabezado.')
            data = dict(zip(header, row))
            result.append({'row_number': reader.line_num, 'name': data['nombre'].strip(),
                           'login': data.get('usuario', '').strip(), 'legajo': data.get('legajo', '').strip()})
            if len(result) > MAX_ROWS:
                raise ValidationError(f'Este envío admite hasta {MAX_ROWS} filas. Cargá un padrón más grande en varios envíos, cada uno con su vista previa, confirmación y CSV de accesos.')
        if not result:
            raise ValidationError('El padrón no tiene personas. Incluí al menos una fila después del encabezado.')
        return result
    except (UnicodeDecodeError, csv.Error, StopIteration, ValueError):
        raise ValidationError('Usá CSV UTF-8 separado por punto y coma, con nombre;usuario. Podés agregar legajo; no se admiten otras columnas.') from None


def spreadsheet_text(value):
    value = str(value or '')
    # El escape es solo de presentación de nombres/metadatos, nunca de accesos.
    if value.lstrip('\ufeff \t\r\n').startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def credentials_csv(reference, company, website_url, rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_ALL, lineterminator='\r\n')
    writer.writerow(['lote', 'empresa', 'nombre', 'usuario', 'contraseña', 'sitio'])
    for name, login, password in rows:
        # La contraseña generada son seis números: sin 0 inicial, que la planilla borraría.
        if not safe_login(login) or not re.fullmatch(r'[A-Za-z1-9][A-Za-z0-9_-]+', password):
            raise ValidationError('No se pudo producir un CSV de accesos seguro. No se creó ninguna cuenta.')
        writer.writerow([spreadsheet_text(reference), spreadsheet_text(company), spreadsheet_text(name),
                         login, password, spreadsheet_text(website_url)])
    return output.getvalue().encode('utf-8-sig')


def runtime_dir(dbname):
    root = Path(config['data_dir']) / 'lafija_credentials' / hashlib.sha256(dbname.encode()).hexdigest()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root.parent, 0o700)
    os.chmod(root, 0o700)
    return root


def credential_path(dbname, token):
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ValueError('Referencia de archivo inválida')
    return runtime_dir(dbname) / (token + '.csv')


def publish_credentials(dbname, token, content):
    path = credential_path(dbname, token)
    temp = path.with_name(uuid.uuid4().hex + '.tmp')
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def purge_credentials(dbname):
    # Incluye archivos huérfanos si el proceso murió antes de confirmar la base.
    for path in runtime_dir(dbname).iterdir():
        if re.fullmatch(r'[0-9a-f]{32}\.(csv|tmp)', path.name):
            try:
                if time.time() - path.stat().st_mtime >= CREDENTIAL_SECONDS:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
