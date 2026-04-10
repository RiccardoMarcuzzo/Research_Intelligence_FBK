import pickle
import joblib
import pandas as pd
import argparse

# questi import sono usati solo per RAG, dal momento che per RANK è stato optato per un lazy loading dentro _topics.py. Valutare se fare lo stesso per RAG.
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction

TITLE = 'RESEARCH INTELLIGENCE'
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

projects_df  = pd.read_parquet('data/docs.parquet')
orgs_df      = pd.read_parquet('data/orgs.parquet')
topics_df    = pd.read_parquet('data/topics.parquet', 
                               columns=['level_1', 'level_2', 'level_3', 'level_4', 'count'])
org_topics_df = pd.read_parquet('data/org_topics.parquet')

with open('data/labels.pkl', 'rb') as f:
    labels_pkl = pickle.load(f)

PROJs_No = projects_df['projectID'].nunique()
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

# Dizionario completo dei codici paese (uppercase come nel dataset)
COUNTRY_CODES = {
    # Europa (UE)
    'AT': 'Austria', 'BE': 'Belgium', 'BG': 'Bulgaria', 'HR': 'Croatia',
    'CY': 'Cyprus', 'CZ': 'Czech Republic', 'DK': 'Denmark', 'EE': 'Estonia',
    'FI': 'Finland', 'FR': 'France', 'DE': 'Germany', 'GR': 'Greece',
    'HU': 'Hungary', 'IE': 'Ireland', 'IT': 'Italy', 'LV': 'Latvia',
    'LT': 'Lithuania', 'LU': 'Luxembourg', 'MT': 'Malta', 'NL': 'Netherlands',
    'PL': 'Poland', 'PT': 'Portugal', 'RO': 'Romania', 'SK': 'Slovakia',
    'SI': 'Slovenia', 'ES': 'Spain', 'SE': 'Sweden',
    
    # Europa (non-UE)
    'AD': 'Andorra', 'AL': 'Albania', 'AM': 'Armenia', 'AZ': 'Azerbaijan',
    'BA': 'Bosnia and Herzegovina', 'BY': 'Belarus', 'CH': 'Switzerland',
    'FO': 'Faroe Islands', 'GE': 'Georgia', 'GB': 'United Kingdom', 
    'GI': 'Gibraltar', 'GL': 'Greenland', 'IS': 'Iceland', 'IM': 'Isle of Man',
    'JE': 'Jersey', 'LI': 'Liechtenstein', 'MC': 'Monaco', 'MD': 'Moldova',
    'ME': 'Montenegro', 'MK': 'North Macedonia', 'NO': 'Norway', 'RS': 'Serbia',
    'RU': 'Russia', 'SM': 'San Marino', 'TR': 'Turkey', 'UA': 'Ukraine',
    'VA': 'Vatican City', 'XK': 'Kosovo', 'YU': 'Yugoslavia',
    
    # Africa
    'AO': 'Angola', 'BF': 'Burkina Faso', 'BI': 'Burundi', 'BJ': 'Benin',
    'BW': 'Botswana', 'CD': 'Congo (DRC)', 'CF': 'Central African Republic',
    'CG': 'Congo', 'CI': "Côte d'Ivoire", 'CM': 'Cameroon', 'CV': 'Cape Verde',
    'DJ': 'Djibouti', 'DZ': 'Algeria', 'EG': 'Egypt', 'ET': 'Ethiopia',
    'GA': 'Gabon', 'GH': 'Ghana', 'GM': 'Gambia', 'GN': 'Guinea',
    'GQ': 'Equatorial Guinea', 'GW': 'Guinea-Bissau', 'KE': 'Kenya',
    'LR': 'Liberia', 'LS': 'Lesotho', 'LY': 'Libya', 'MA': 'Morocco',
    'MG': 'Madagascar', 'ML': 'Mali', 'MR': 'Mauritania', 'MU': 'Mauritius',
    'MW': 'Malawi', 'MZ': 'Mozambique', 'NA': 'Namibia', 'NE': 'Niger',
    'NG': 'Nigeria', 'RW': 'Rwanda', 'SC': 'Seychelles', 'SD': 'Sudan',
    'SL': 'Sierra Leone', 'SN': 'Senegal', 'SO': 'Somalia', 'ST': 'São Tomé and Príncipe',
    'SZ': 'Eswatini', 'TD': 'Chad', 'TG': 'Togo', 'TN': 'Tunisia',
    'TZ': 'Tanzania', 'UG': 'Uganda', 'ZA': 'South Africa', 'ZM': 'Zambia',
    'ZW': 'Zimbabwe',
    
    # Asia
    'AE': 'United Arab Emirates', 'AF': 'Afghanistan', 'BD': 'Bangladesh',
    'BH': 'Bahrain', 'BN': 'Brunei', 'BT': 'Bhutan', 'CN': 'China',
    'HK': 'Hong Kong', 'ID': 'Indonesia', 'IL': 'Israel', 'IN': 'India',
    'IQ': 'Iraq', 'IR': 'Iran', 'JO': 'Jordan', 'JP': 'Japan',
    'KG': 'Kyrgyzstan', 'KH': 'Cambodia', 'KR': 'South Korea', 'KW': 'Kuwait',
    'KZ': 'Kazakhstan', 'LA': 'Laos', 'LB': 'Lebanon', 'LK': 'Sri Lanka',
    'MM': 'Myanmar', 'MN': 'Mongolia', 'MO': 'Macau', 'MV': 'Maldives',
    'MY': 'Malaysia', 'NP': 'Nepal', 'OM': 'Oman', 'PK': 'Pakistan',
    'PH': 'Philippines', 'PS': 'Palestine', 'QA': 'Qatar', 'SA': 'Saudi Arabia',
    'SG': 'Singapore', 'SY': 'Syria', 'TH': 'Thailand', 'TJ': 'Tajikistan',
    'TM': 'Turkmenistan', 'TW': 'Taiwan', 'UZ': 'Uzbekistan', 'VN': 'Vietnam',
    'YE': 'Yemen',
    
    # Americas
    'AR': 'Argentina', 'AW': 'Aruba', 'BB': 'Barbados', 'BQ': 'Bonaire',
    'BR': 'Brazil', 'BZ': 'Belize', 'CA': 'Canada', 'CL': 'Chile',
    'CO': 'Colombia', 'CR': 'Costa Rica', 'CU': 'Cuba', 'DO': 'Dominican Republic',
    'EC': 'Ecuador', 'FK': 'Falkland Islands', 'GD': 'Grenada', 'GT': 'Guatemala',
    'GU': 'Guam', 'HN': 'Honduras', 'HT': 'Haiti', 'JM': 'Jamaica',
    'KY': 'Cayman Islands', 'LC': 'Saint Lucia', 'MX': 'Mexico', 'NI': 'Nicaragua',
    'PA': 'Panama', 'PE': 'Peru', 'PY': 'Paraguay', 'SR': 'Suriname',
    'SV': 'El Salvador', 'SX': 'Sint Maarten', 'TT': 'Trinidad and Tobago',
    'UM': 'U.S. Minor Outlying Islands', 'US': 'United States', 'UY': 'Uruguay',
    'VE': 'Venezuela', 'VG': 'British Virgin Islands',
    
    # Oceania
    'AU': 'Australia', 'FJ': 'Fiji', 'MH': 'Marshall Islands', 'MP': 'Northern Mariana Islands',
    'NC': 'New Caledonia', 'NF': 'Norfolk Island', 'NU': 'Niue', 'NZ': 'New Zealand',
    'PF': 'French Polynesia', 'PG': 'Papua New Guinea', 'SB': 'Solomon Islands',
    'VU': 'Vanuatu', 'WF': 'Wallis and Futuna', 'WS': 'Samoa',
    
}

# Lista codici UE (per l'opzione EU)
EU_COUNTRY_CODES = [
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 
    'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 
    'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE'
]