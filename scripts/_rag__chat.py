import requests

from utils import projects_df, COUNTRY_CODES
from scripts._rag import THRESHOLD
from llm_settings import get_llm_url, get_llm_model

FP_LABELS = {8: 'Horizon 2020', 9: 'Horizon Europe'}
ORG_TYPE_LABELS = {
    'REC': 'Research organisation',
    'HES': 'Higher education establishment',
    'PRC': 'Private for-profit company',
    'PUB': 'Public body',
    'OTH': 'Other',
}

SYSTEM_PROMPT_TEMPLATE = (
    "You are a research assistant answering questions about a single EU-funded "
    "research project. Base your answers only on the information below; if the "
    "answer isn't contained in it, say so instead of guessing.\n\n"
    "Title: {title}\n\n"
    "Objective: {objective}"
    "{query_section}"
)

QUERY_SECTION_TEMPLATE = (
    "\n\n---\n"
    "This project was surfaced by a search tool. Use the details below only if the "
    "user asks about the relevance, ranking, or match quality of this project to "
    "their search:\n"
    "{description}"
)


def get_project_context(project_id):
    row = projects_df[projects_df['projectID'] == project_id].iloc[0]
    return row['title'], row['objective']


def describe_query_context(query_context, project_id):
    if not query_context:
        return ''

    lines = []

    query_text = query_context.get('query_text')
    if query_text:
        lines.append(f'Free-text search query: "{query_text}"')

    filter_descriptions = []
    fp_list = query_context.get('fp') or []
    if fp_list:
        filter_descriptions.append('Framework Programme: ' + ', '.join(FP_LABELS.get(fp, str(fp)) for fp in fp_list))

    country_list = query_context.get('country') or []
    if country_list:
        filter_descriptions.append('Country: ' + ', '.join(COUNTRY_CODES.get(c, c) for c in country_list))

    org_type_list = query_context.get('org_type') or []
    if org_type_list:
        filter_descriptions.append('Organisation type: ' + ', '.join(ORG_TYPE_LABELS.get(t, t) for t in org_type_list))

    org_list = query_context.get('org') or []
    if org_list:
        filter_descriptions.append('Organisation: ' + ', '.join(org_list))

    topic_list = query_context.get('topic') or []
    if topic_list:
        filter_descriptions.append('Topic: ' + ', '.join(topic_list))

    if filter_descriptions:
        lines.append('Active filters: ' + '; '.join(filter_descriptions))

    score = (query_context.get('scores') or {}).get(str(project_id))
    if score is not None:
        lines.append(
            f'Semantic similarity score between the query and this project: {score:.3f} '
            f'(cosine similarity, range -1 to 1, higher means more relevant; projects below '
            f'{THRESHOLD} are not returned by the search).'
        )

    return '\n'.join(lines)


RELEVANCE_SYSTEM_TEMPLATE = (
    "You are a research assistant. Explain in exactly 1-2 sentences why the research "
    "project below is relevant to the user's search, referencing specific details from "
    "the objective and the query rather than generic praise. Do not repeat the title "
    "verbatim, and do not mention that you were given instructions.\n\n"
    "Title: {title}\n\n"
    "Objective: {objective}\n\n"
    "{query_description}"
)


def explain_relevance(project_id, query_context):
    title, objective = get_project_context(project_id)
    query_description = describe_query_context(query_context, project_id)

    messages = [
        {
            'role': 'system',
            'content': RELEVANCE_SYSTEM_TEMPLATE.format(
                title=title, objective=objective, query_description=query_description
            ),
        },
        {'role': 'user', 'content': 'Why is this project relevant to my search?'},
    ]

    model = get_llm_model()
    response = requests.post(
        f"{get_llm_url()}/api/chat",
        json={'model': model, 'messages': messages, 'stream': False},
        timeout=120,
    )
    response.raise_for_status()

    return response.json()['message']['content'], model


def ask_project_chat(project_id, user_message, history, query_context=None):
    title, objective = get_project_context(project_id)

    query_description = describe_query_context(query_context, project_id)
    query_section = QUERY_SECTION_TEMPLATE.format(description=query_description) if query_description else ''

    system_message = {
        'role': 'system',
        'content': SYSTEM_PROMPT_TEMPLATE.format(title=title, objective=objective, query_section=query_section),
    }
    messages = [system_message] + history + [{'role': 'user', 'content': user_message}]

    response = requests.post(
        f"{get_llm_url()}/api/chat",
        json={'model': get_llm_model(), 'messages': messages, 'stream': False},
        timeout=120,
    )
    response.raise_for_status()

    return response.json()['message']['content']
