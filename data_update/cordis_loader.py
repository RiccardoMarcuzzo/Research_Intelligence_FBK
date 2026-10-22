# ------------------------------------------------------------------------------
# Lettura di un export CORDIS (Data Extraction Tool) in uno dei due formati:
#
#   legacy   (fino al 2026-05): file tabellari unici, project.json, organization.json,
#            webLink.json, ...; i nomi delle colonne sono in [columns] di settings.config
#   records  (dal 2026-05-06): un file per progetto, project-rcn-<rcn>_<lang>.json, con
#            struttura gerarchica come l'XML; partecipanti e deliverables sono annidati
#            in relations.associations
#
# Il formato viene riconosciuto dal contenuto della cartella. Qualunque sia il formato,
# le funzioni load_* restituiscono gli stessi DataFrame, con i nomi di colonna usati
# da update_db.py.
# ------------------------------------------------------------------------------

import json
import os
from glob import glob

import pandas as pd

LEGACY = 'legacy'
RECORDS = 'records'

LEGACY_PROJECTS_FILE = 'project.json'
LEGACY_ORGS_FILE = 'organization.json'
LEGACY_WEBLINKS_FILE = 'webLink.json'
RECORD_PATTERN = 'project-rcn-*.json'

PROJECT_COLUMNS = ['projectID', 'title', 'objective', 'fp', 'acronym']
ORG_COLUMNS = ['organisationID', 'name', 'countryCode', 'activityType', 'role',
               'netEcContribution', 'projectID']
WEBLINK_COLUMNS = ['id', 'projectID', 'physUrl', 'type']
DELIVERABLE_COLUMNS = ['id', 'projectID', 'title', 'physUrl']


class CordisFormatError(Exception):
    pass


def detect_format(folder):
    """'legacy' se la cartella contiene project.json, 'records' se contiene i file
    project-rcn-*.json. Errore se non contiene nessuno dei due o li contiene entrambi."""
    if not os.path.isdir(folder):
        raise CordisFormatError(f'New data folder not found: {folder}')
    legacy = os.path.exists(os.path.join(folder, LEGACY_PROJECTS_FILE))
    records = bool(glob(os.path.join(folder, RECORD_PATTERN)))
    if legacy and records:
        raise CordisFormatError(f'{folder} contains both {LEGACY_PROJECTS_FILE} and '
                                f'{RECORD_PATTERN} files: keep only one export per folder.')
    if legacy:
        return LEGACY
    if records:
        return RECORDS
    raise CordisFormatError(f'{folder} contains neither {LEGACY_PROJECTS_FILE} nor '
                            f'{RECORD_PATTERN} files: is it a CORDIS export?')


def _legacy_columns(columns, keys):
    missing = [k for k in keys if not (columns or {}).get(k)]
    if missing:
        raise CordisFormatError(f'Old-format export: missing {missing} in the [columns] '
                                'section of settings.config')
    return [columns[k] for k in keys]


def load_projects(folder, columns):
    """Progetti dell'export: projectID, title, objective, fp (sigla, es. 'HORIZON'), acronym.
    columns: sezione [columns] di settings.config (usata solo dal formato legacy).
    Nel formato legacy l'ordine è quello di project.json, nel formato records i progetti
    sono ordinati per projectID: gli embedding precalcolati (.npy) seguono questo ordine."""
    if detect_format(folder) == LEGACY:
        df = pd.read_json(os.path.join(folder, LEGACY_PROJECTS_FILE))
        df = df[_legacy_columns(columns, ['proj_id', 'proj_title', 'proj_objective',
                                          'proj_fp', 'proj_acronym'])]
        return df.rename(columns={columns['proj_id']: 'projectID',
                                  columns['proj_title']: 'title',
                                  columns['proj_objective']: 'objective',
                                  columns['proj_fp']: 'fp',
                                  columns['proj_acronym']: 'acronym'})

    rows = [_record_project(r) for r in _iter_records(folder)]
    df = pd.DataFrame(rows, columns=PROJECT_COLUMNS)
    df['projectID'] = _to_id(df['projectID'])
    dup = df.loc[df['projectID'].duplicated(), 'projectID']
    if not dup.empty:
        raise CordisFormatError(f'Projects in more than one file of {folder}: '
                                f'{sorted(dup.unique().tolist())[:10]}')
    return df.sort_values('projectID', kind='stable').reset_index(drop=True)


def load_organizations(folder, columns):
    """Partecipazioni (una riga per organizzazione e progetto): organisationID, name (nome
    legale, non ancora formattato), countryCode (può contenere più paesi, es. 'DE;HU'),
    activityType (es. 'PRC'), role, netEcContribution (numerico), projectID."""
    if detect_format(folder) == LEGACY:
        df = pd.read_json(os.path.join(folder, LEGACY_ORGS_FILE))
        df = df[_legacy_columns(columns, ['org_id', 'org_name', 'org_country_code',
                                          'org_activity_type', 'org_role',
                                          'org_proj_ec_contribution', 'org_proj_id'])]
        return df.rename(columns={columns['org_id']: 'organisationID',
                                  columns['org_name']: 'name',
                                  columns['org_country_code']: 'countryCode',
                                  columns['org_activity_type']: 'activityType',
                                  columns['org_role']: 'role',
                                  columns['org_proj_ec_contribution']: 'netEcContribution',
                                  columns['org_proj_id']: 'projectID'})

    rows = [row for r in _iter_records(folder) for row in _record_orgs(r)]
    df = pd.DataFrame(rows, columns=ORG_COLUMNS)
    df['organisationID'] = _to_id(df['organisationID'])
    df['projectID'] = _to_id(df['projectID'])
    df['netEcContribution'] = pd.to_numeric(df['netEcContribution'], errors='coerce')
    return df


def load_weblinks(folder):
    """Web link dell'export (id, projectID, physUrl, type), come webLink.json del formato
    legacy. I deliverables sono quelli con type == 'projectDeliverable'."""
    if detect_format(folder) == LEGACY:
        df = pd.read_json(os.path.join(folder, LEGACY_WEBLINKS_FILE))
        return df[WEBLINK_COLUMNS]

    rows = [row for r in _iter_records(folder) for row in _record_weblinks(r)]
    df = pd.DataFrame(rows, columns=WEBLINK_COLUMNS)
    df['projectID'] = _to_id(df['projectID'])
    return df


def load_deliverables(folder):
    """Deliverables dell'export: id (stringa CORDIS, es. '101069359_20_DELIVHORIZON'),
    projectID, title (titolo ufficiale), physUrl (None se il deliverable non ha un link).
    Solo formato records: il vecchio export non ha i titoli dei deliverables."""
    if detect_format(folder) == LEGACY:
        raise CordisFormatError(f'{folder} is an old-format export: deliverable titles are '
                                'only in the format with one file per project.')

    rows = [row for r in _iter_records(folder) for row in _record_deliverables(r)]
    df = pd.DataFrame(rows, columns=DELIVERABLE_COLUMNS)
    df['projectID'] = _to_id(df['projectID'])
    dup = df.loc[df['id'].duplicated(), 'id']
    if not dup.empty:
        raise CordisFormatError(f'Deliverables in more than one project of {folder}: '
                                f'{sorted(dup.unique().tolist())[:10]}')
    return df


# ------------------------------------------------------------------------------
# formato records
# ------------------------------------------------------------------------------
def _iter_records(folder):
    for path in sorted(glob(os.path.join(folder, RECORD_PATTERN))):
        with open(path, encoding='utf-8') as f:
            record = json.load(f)
        if record.get('contenttype') != 'project':
            raise CordisFormatError(f'{path} is not a project record '
                                    f"(contenttype: {record.get('contenttype')!r})")
        yield record


def _associations(item, contenttype):
    return [a for a in (item.get('relations') or {}).get('associations') or []
            if a.get('contenttype') == contenttype]


def _categories(item, classification):
    return [c for c in (item.get('relations') or {}).get('categories') or []
            if (c.get('attributes') or {}).get('classification') == classification]


def _record_project(record):
    # il framework programme non è più un campo del progetto: è nei programmi collegati
    # (legal basis e topic), che hanno tutti lo stesso
    programmes = _associations(record, 'programme')
    programmes.sort(key=lambda p: (p.get('attributes') or {}).get('type') != 'relatedLegalBasis')
    fp = next((p['frameworkProgramme'] for p in programmes if p.get('frameworkProgramme')), None)
    return {
        'projectID': record.get('id'),
        'title': record.get('title'),
        'objective': record.get('objective'),
        'fp': fp,
        'acronym': record.get('acronym'),
    }


def _record_orgs(record):
    for org in _associations(record, 'organization'):
        attrs = org.get('attributes') or {}
        activity = _categories(org, 'organizationActivityType')
        yield {
            'organisationID': org.get('id'),
            'name': org.get('legalName'),
            'countryCode': (org.get('address') or {}).get('country'),
            # i codici delle categorie hanno uno slash davanti ('/PRC')
            'activityType': activity[0]['code'].lstrip('/') if activity else None,
            'role': attrs.get('type'),
            'netEcContribution': attrs.get('netEcContribution'),
            'projectID': record.get('id'),
        }


def _record_weblinks(record):
    # i link dei deliverables sono annidati nei risultati del progetto
    for item in [record] + _associations(record, 'result'):
        for link in _associations(item, 'webLink'):
            yield {
                'id': link.get('id'),
                'projectID': record.get('id'),
                'physUrl': link.get('physUrl'),
                'type': (link.get('attributes') or {}).get('type'),
            }


def _record_deliverables(record):
    # i deliverables sono i risultati della collection '/deliverable', con al più un
    # webLink 'projectDeliverable' (il pdf)
    for result in _associations(record, 'result'):
        if not any(c.get('code') == '/deliverable' for c in _categories(result, 'collection')):
            continue
        links = [l for l in _associations(result, 'webLink')
                 if (l.get('attributes') or {}).get('type') == 'projectDeliverable']
        yield {
            'id': result.get('id'),
            'projectID': record.get('id'),
            'title': result.get('title'),
            'physUrl': links[0].get('physUrl') if links else None,
        }


def _to_id(series):
    """Id da stringa a intero. Un id non numerico lascia la colonna float con NaN:
    update_db.py controlla il dtype e si ferma."""
    ids = pd.to_numeric(series, errors='coerce')
    return ids.astype('int64') if ids.notna().all() else ids
