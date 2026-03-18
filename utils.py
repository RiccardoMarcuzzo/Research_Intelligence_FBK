import pickle
import joblib
import pandas as pd
import argparse

# questi import sono usati solo per RAG, dal momento che per RANK è stato optato per un lazy loading dentro _topics.py. Valutare se fare lo stesso per RAG.
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

TITLE = 'Ex-CORDIS'
GOOGLE_API = 'non_disponibile' #TODO: TO-REMOVE-ASKAI-RAG

# Configurazione CLI 
parser = argparse.ArgumentParser(description="Lancio della Dashboard Dash")

parser.add_argument("--path", type=str, default="/research_intelligence/", help="Percorso base dell'app (es: /research_intelligence/)")
parser.add_argument("--port", type=int, default=8050, help="Porta di esecuzione")
args = parser.parse_args()

# Pulizia del path
base_path = args.path
if not base_path.startswith('/'): base_path = '/' + base_path
if not base_path.endswith('/'): base_path = base_path + '/'

PORT = args.port

projects_df  = pd.read_parquet('data/docs.parquet',
                               columns=['id', 'title', 'objective', 'fp', 'topic_name'])
orgs_df      = pd.read_parquet('data/orgs.parquet', 
                               columns=['name', 'projectIDs', 'country_code_ok', 
                                        'organizationURL', 'activityType',
                                        'organisationID'])
topics_df    = pd.read_parquet('data/topics.parquet', 
                               columns=['level_1', 'level_2', 'level_3', 'level_4'])
org_topics_df = pd.read_parquet('data/org_topics.parquet',
                                columns=['organisationID', 'fp', 'topic_name_hierarchy',
                                         'n_proj', 'netEcContribution', 'n_publ', 
                                         'projIds', 'scopus_id', 'country_code_ok',
                                         'name']) # se usiamo anche 'role', a quel punto vengono usate tutte

with open('data/labels.pkl', 'rb') as f:
    labels_pkl = pickle.load(f)

PROJs_No = projects_df['id'].nunique()
ORGs_No = orgs_df['organisationID'].nunique()
TOPs_No = len(labels_pkl)

# caricamento per il ranking dei topic suggestion
topic_rank_assets = joblib.load('data/topic_search_assets_all.pkl')
TOPIC_IDS = topic_rank_assets['topic_ids']
TOPIC_EMBS = topic_rank_assets['embeddings']
BM25 = topic_rank_assets['bm25_model']

# caricamento per il RAG system (bloccato) #TODO: TO-REMOVE-ASKAI-RAG
RAG_EMBS = None
RAG_TOKENIZER = None
RAG_MODEL = None
"""
RAG_EMBS = np.load('data/bge_1024dim.npy')
RAG_TOKENIZER = AutoTokenizer.from_pretrained('data/bge-m3-onnx')
RAG_MODEL = ORTModelForFeatureExtraction.from_pretrained('data/bge-m3-onnx', provider='CPUExecutionProvider')
"""

# Dizionario completo dei codici paese (lowercase come nel dataset)
COUNTRY_CODES = {
    # Europa (UE)
    'at': 'Austria', 'be': 'Belgium', 'bg': 'Bulgaria', 'hr': 'Croatia',
    'cy': 'Cyprus', 'cz': 'Czech Republic', 'dk': 'Denmark', 'ee': 'Estonia',
    'fi': 'Finland', 'fr': 'France', 'de': 'Germany', 'gr': 'Greece',
    'hu': 'Hungary', 'ie': 'Ireland', 'it': 'Italy', 'lv': 'Latvia',
    'lt': 'Lithuania', 'lu': 'Luxembourg', 'mt': 'Malta', 'nl': 'Netherlands',
    'pl': 'Poland', 'pt': 'Portugal', 'ro': 'Romania', 'sk': 'Slovakia',
    'si': 'Slovenia', 'es': 'Spain', 'se': 'Sweden',
    
    # Europa (non-UE)
    'ad': 'Andorra', 'al': 'Albania', 'am': 'Armenia', 'az': 'Azerbaijan',
    'ba': 'Bosnia and Herzegovina', 'by': 'Belarus', 'ch': 'Switzerland',
    'fo': 'Faroe Islands', 'ge': 'Georgia', 'gb': 'United Kingdom', 
    'gi': 'Gibraltar', 'gl': 'Greenland', 'is': 'Iceland', 'im': 'Isle of Man',
    'je': 'Jersey', 'li': 'Liechtenstein', 'mc': 'Monaco', 'md': 'Moldova',
    'me': 'Montenegro', 'mk': 'North Macedonia', 'no': 'Norway', 'rs': 'Serbia',
    'ru': 'Russia', 'sm': 'San Marino', 'tr': 'Turkey', 'ua': 'Ukraine',
    'va': 'Vatican City', 'xk': 'Kosovo', 'yu': 'Yugoslavia',
    
    # Africa
    'ao': 'Angola', 'bf': 'Burkina Faso', 'bi': 'Burundi', 'bj': 'Benin',
    'bw': 'Botswana', 'cd': 'Congo (DRC)', 'cf': 'Central African Republic',
    'cg': 'Congo', 'ci': "Côte d'Ivoire", 'cm': 'Cameroon', 'cv': 'Cape Verde',
    'dj': 'Djibouti', 'dz': 'Algeria', 'eg': 'Egypt', 'et': 'Ethiopia',
    'ga': 'Gabon', 'gh': 'Ghana', 'gm': 'Gambia', 'gn': 'Guinea',
    'gq': 'Equatorial Guinea', 'gw': 'Guinea-Bissau', 'ke': 'Kenya',
    'lr': 'Liberia', 'ls': 'Lesotho', 'ly': 'Libya', 'ma': 'Morocco',
    'mg': 'Madagascar', 'ml': 'Mali', 'mr': 'Mauritania', 'mu': 'Mauritius',
    'mw': 'Malawi', 'mz': 'Mozambique', 'na': 'Namibia', 'ne': 'Niger',
    'ng': 'Nigeria', 'rw': 'Rwanda', 'sc': 'Seychelles', 'sd': 'Sudan',
    'sl': 'Sierra Leone', 'sn': 'Senegal', 'so': 'Somalia', 'st': 'São Tomé and Príncipe',
    'sz': 'Eswatini', 'td': 'Chad', 'tg': 'Togo', 'tn': 'Tunisia',
    'tz': 'Tanzania', 'ug': 'Uganda', 'za': 'South Africa', 'zm': 'Zambia',
    'zw': 'Zimbabwe',
    
    # Asia
    'ae': 'United Arab Emirates', 'af': 'Afghanistan', 'bd': 'Bangladesh',
    'bh': 'Bahrain', 'bn': 'Brunei', 'bt': 'Bhutan', 'cn': 'China',
    'hk': 'Hong Kong', 'id': 'Indonesia', 'il': 'Israel', 'in': 'India',
    'iq': 'Iraq', 'ir': 'Iran', 'jo': 'Jordan', 'jp': 'Japan',
    'kg': 'Kyrgyzstan', 'kh': 'Cambodia', 'kr': 'South Korea', 'kw': 'Kuwait',
    'kz': 'Kazakhstan', 'la': 'Laos', 'lb': 'Lebanon', 'lk': 'Sri Lanka',
    'mm': 'Myanmar', 'mn': 'Mongolia', 'mo': 'Macau', 'mv': 'Maldives',
    'my': 'Malaysia', 'np': 'Nepal', 'om': 'Oman', 'pk': 'Pakistan',
    'ph': 'Philippines', 'ps': 'Palestine', 'qa': 'Qatar', 'sa': 'Saudi Arabia',
    'sg': 'Singapore', 'sy': 'Syria', 'th': 'Thailand', 'tj': 'Tajikistan',
    'tm': 'Turkmenistan', 'tw': 'Taiwan', 'uz': 'Uzbekistan', 'vn': 'Vietnam',
    'ye': 'Yemen',
    
    # Americas
    'ar': 'Argentina', 'aw': 'Aruba', 'bb': 'Barbados', 'bq': 'Bonaire',
    'br': 'Brazil', 'bz': 'Belize', 'ca': 'Canada', 'cl': 'Chile',
    'co': 'Colombia', 'cr': 'Costa Rica', 'cu': 'Cuba', 'do': 'Dominican Republic',
    'ec': 'Ecuador', 'fk': 'Falkland Islands', 'gd': 'Grenada', 'gt': 'Guatemala',
    'gu': 'Guam', 'hn': 'Honduras', 'ht': 'Haiti', 'jm': 'Jamaica',
    'ky': 'Cayman Islands', 'lc': 'Saint Lucia', 'mx': 'Mexico', 'ni': 'Nicaragua',
    'pa': 'Panama', 'pe': 'Peru', 'py': 'Paraguay', 'sr': 'Suriname',
    'sv': 'El Salvador', 'sx': 'Sint Maarten', 'tt': 'Trinidad and Tobago',
    'um': 'U.S. Minor Outlying Islands', 'us': 'United States', 'uy': 'Uruguay',
    've': 'Venezuela', 'vg': 'British Virgin Islands',
    
    # Oceania
    'au': 'Australia', 'fj': 'Fiji', 'mh': 'Marshall Islands', 'mp': 'Northern Mariana Islands',
    'nc': 'New Caledonia', 'nf': 'Norfolk Island', 'nu': 'Niue', 'nz': 'New Zealand',
    'pf': 'French Polynesia', 'pg': 'Papua New Guinea', 'sb': 'Solomon Islands',
    'vu': 'Vanuatu', 'wf': 'Wallis and Futuna', 'ws': 'Samoa',
    
}

# Lista codici UE (per l'opzione EU)
EU_COUNTRY_CODES = [
    'at', 'be', 'bg', 'hr', 'cy', 'cz', 'dk', 'ee', 'fi', 'fr', 
    'de', 'gr', 'hu', 'ie', 'it', 'lv', 'lt', 'lu', 'mt', 'nl', 
    'pl', 'pt', 'ro', 'sk', 'si', 'es', 'se'
]

