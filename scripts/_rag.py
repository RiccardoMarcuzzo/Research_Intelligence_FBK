import torch
import re
#from google import genai #TODO: de-comment
#from google.api_core.exceptions import ServerError, ServiceUnavailable #TODO: de-comment
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from dash import html

from utils import projects_df, RAG_TOKENIZER, RAG_MODEL, RAG_EMBS, GOOGLE_API

# TODO: de-comment

'''
client = genai.Client(api_key=GOOGLE_API)
GEMINI_MODEL = 'gemini-2.5-flash'

titles = projects_df['title'].to_list()
objs = projects_df['objective'].to_list()
fps = projects_df['fp'].to_list()

TEST = False

def encode(text, max_length=8192):

    inputs = RAG_TOKENIZER(
        text,
        max_length=max_length,
        padding=True,
        truncation=True,
        return_tensors='pt'
    )

    outputs = RAG_MODEL(**inputs)
    
    embeddings = outputs.last_hidden_state[:, 0, :]
    
    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
    
    return embeddings.detach().cpu().numpy()


def create_prompt(QUERY, DOCS=[], prompt_type=1):
  if prompt_type == 1:
    return f"""### ROLE
You are a Research Intelligence Assistant specializing in the CORDIS project database (1984–Present). Your goal is to verify if specific research directions have been previously funded and to synthesize the findings from relevant projects.

### CONTEXT: RETRIEVED PROJECTS
The following project objectives have been retrieved based on semantic similarity to the user's query:
{'\n'.join(DOCS)}

### INSTRUCTIONS
1.  **Synthesize, Don't Just List:** Group projects with similar methodologies or objectives. Provide a cohesive overview of how this research area has been addressed.
2.  **Strict Adherence:** Base your answer *entirely* on the provided summaries. If the documents mention a specific technology or result, you may include it. Do not use external knowledge.
3.  **Citation & Traceability:** You must cite the document index for every claim. Use the format: "Project \[index\] investigated X" (eg. \[1\], \[7\])  to refer to documents)
4.  **Chronological Awareness:** CORDIS data spans 40 years. If relevant, briefly note if the research is historical (e.g., FP4/FP5) or contemporary (Horizon Europe) to give the researcher a sense of the field's evolution.
5.  **Exclusion:** If a retrieved document is a "false positive" (semantically similar but contextually irrelevant), ignore it.

### OUTPUT FORMAT
* **Direct Answer:** Start with a clear statement on the extent to which the query research has been performed.
* **Detailed Analysis:** Use bullet points or paragraphs.
* Maintain the same language as the user query.

### FORMATTING RULES
* **Use Markdown:** Use ### for sections and #### for sub-sections.
* **Visual Hierarchy:** Use **bold** for key terms and bullet points for lists.
* **Clarity:** Ensure the response is scannable and not a wall of text.
* **Formatting:** Underline all direct citations from the text.
* **Citing:** Use notation \[index\] (eg. \[1\], \[7\])  to refer to documents.

### USER QUERY
{QUERY}

### RESPONSE
"""

  elif prompt_type == 2:
    return f"""### ROLE
You are a Research Discovery Scout. The system has not found a direct match for the user's specific query in the CORDIS database, but it has identified "Adjacent Research"—projects that share methodologies, technologies, or contexts. Your goal is to map these connections to help the researcher refine their scope or identify novel gaps.

### CONTEXT: ADJACENT PROJECTS
The following projects were retrieved as semantically related, though they do not address the query directly:
{'\n'.join(DOCS)}

### INSTRUCTIONS
1.  **Acknowledge the Gap:** Start by stating clearly that no direct match was found for "{QUERY}", but identify the "proximal" fields that *are* represented.
2.  **Identify the Pivot:** Explain *why* these documents are relevant. (e.g., "While you asked for X, the current funding landscape shows significant activity in Y, which uses similar mechanisms.")
3.  **Propositive Analysis:** Use the retrieved documents to suggest how the user might refine their research or where their query fits into the broader EU research ecosystem.
4.  **Strict Source Control:** Only use the provided documents. If a document is irrelevant to even an exploratory view, omit it.
5.  **Citation:** Underline all specific findings and cite the index (\[index\], eg. \[1\], \[7\],  to refer to documents).

### OUTPUT STRUCTURE
* **Gap Statement:** A brief sentence on the lack of direct matches.
* **Research Map:** A synthesis of the "adjacent" findings.
* **Strategic Suggestions:** 1-2 suggestions on how the user might pivot their query based on what *was* found.
* Maintain the same language as the user query.

### FORMATTING RULES
* **Use Markdown:** Use ### for sections and #### for sub-sections.
* **Visual Hierarchy:** Use **bold** for key terms and bullet points for lists.
* **Clarity:** Ensure the response is scannable and not a wall of text.
* **Formatting:** Underline all direct citations from the text.
* **Citing:** Use notation \[index\] (eg. \[1\], \[7\]) to refer to documents.

### USER QUERY
{QUERY}

### RESPONSE
"""

  elif prompt_type == 3:
    return f"""### ROLE
You are a Research Consultant for the CORDIS database. The retrieval system has returned zero relevant matches for the user's query. Your goal is to explain this absence constructively and provide actionable advice on how to adjust their search strategy to navigate 40 years of EU research data.

### DIAGNOSTIC INSTRUCTIONS
1.  **Acknowledge the Outcome:** State clearly that no projects matching "{QUERY}" were found in the CORDIS archives (1984–Present).
2.  **The "Novelty" Perspective:** Frame the absence of results positively—it may indicate a highly novel research area or a niche that has not yet received specific EU funding.
3.  **Strategic Recommendations:** * If the query was **too specific** (e.g., a very niche product name or specific local site), suggest using broader technical terms or methodologies.
    * If the query was **too broad** (e.g., "Green energy"), suggest adding specific constraints like a technology (e.g., "Photovoltaic thin-film") or a timeframe.
    * Suggest checking for **Synonyms**: Remind the user that older projects (FP4/FP5) might use different terminology than modern Horizon Europe projects.
4.  **Tone:** Professional, encouraging, and analytical.

### OUTPUT FORMAT
* **Status Report:** A brief statement on the lack of matches.
* **Search Optimization Tips:** Bullet points with specific ways to rephrase the query.
* Maintain the same language as the user query.

### FORMATTING RULES
* **Use Markdown:** Use ### for sections and #### for sub-sections.
* **Visual Hierarchy:** Use **bold** for key terms and bullet points for lists.
* **Clarity:** Ensure the response is scannable and not a wall of text.

### USER QUERY
{QUERY}

### RESPONSE
"""

def rag_prompt_system(query):
    query_emb = encode(query, max_length=8192).reshape(1, -1)
    cos_scores = cosine_similarity(query_emb, RAG_EMBS)[0]
    best_indices = np.argsort(cos_scores)[::-1][:15]
    
    top_score = cos_scores[best_indices[0]]
    
    if top_score > 0.60:
        threshold, prompt_type = 0.60, 1
    elif top_score > 0.50:
        threshold, prompt_type = 0.50, 2
    else:
        return create_prompt(query, prompt_type=3), {}, 3
    
    valid_mask = cos_scores[best_indices] > threshold
    valid_indices = best_indices[valid_mask]
    
    DOCS = [
        f"{i+1}-{titles[idx].upper()}\n{cos_scores[idx]}\nFramework programme: {fps[idx]}\n{objs[idx]}"
        for i, idx in enumerate(valid_indices)
    ]
    DOCS_MAPPING = {i+1: idx for i, idx in enumerate(valid_indices)}    
    prompt = create_prompt(query, DOCS, prompt_type=prompt_type)

    return prompt, DOCS_MAPPING, prompt_type

def make_sidebar_content(text, mapping, prompt_type):
    sources = {'used': {}}
    # Trova i vari [1], [2] ecc nel testo
    for match in re.finditer(r"\\\[(\d+)\\\]", text):
        id = int(match.group(1))
        sources['used'][id] = mapping[id]
    if prompt_type == 1:
        sources['unused'] = [v for v in mapping.values() if v not in sources['used'].values()]
    
    return sources

def make_router(query, context):
    last_msg = context[-1]['content'] if context else "No previous context"

    prompt = f"""Task: Classify the USER_QUERY.
Context (last AI message): {last_msg}
USER_QUERY: "{query}"

Categories:
- Research: Searching for data, projects, funding, or specific scientific topics, e.g. 'Are there studies about X?', 'Has ever been funded Y?', 'I want to investigate Z.' 
- Conversation: Greetings, thanks, meta-questions about the assistant, or clarifying information already provided, e.g. 'What can you do', 'Explain document 2' 

Constraint: Respond with ONLY the word 'Research' or 'Conversation'.

Classification:"""

    response = client.models.generate_content(
        model='gemma-3-27b-it',
        contents=prompt,
    )
    
    category = response.text.strip().capitalize().replace('.', '').replace('"', '')
    
    if 'Research' in category:
        return 'Research'
    return 'Conversation'

def ask_rag(query, context):
    if TEST:
        prompt, mapping, prompt_type = rag_prompt_system(query)
        return prompt, {'used': [], 'unused': []}

    if len(context) <= 2:
        prompt, mapping, prompt_type = rag_prompt_system(query)
    
    else:
        routing = make_router(query, context)
        if routing == 'Research':
            prompt, mapping, prompt_type = rag_prompt_system(query)
        else: # routing == 'Conversation':
            history = "\n".join([f"{msg['role']}: {msg['content']}" for msg in context])          
            prompt = (
                f"History of conversation:\n{history}\n\n"
                f"User query: {query}\n\n"
                "Instruction: Answer the user's last message based on the context above. "
                "Maintain the same language as the user query."
            )
            mapping = {}
            prompt_type = 4
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
            'temperature': 0.1,
            'top_p': 0.95,}
        )
        return response.text, make_sidebar_content(response.text, mapping, prompt_type)
    except (ServerError, ServiceUnavailable) as e: # cattura Error 503
        prompt = f'ERROR API GOOGLE: {e}\nPrompt used:\n\n' + prompt
        return prompt, {'used': [], 'unused': []}

#SIDEBAR
def create_project_block(row, citation_number=None):
    title = row['title']
    display_title = f"[{citation_number}] - {title}" if citation_number else title
    
    return html.Details([
        html.Summary(display_title, style={
            'fontWeight': 'bold',
            'fontSize': '16px',
            'cursor': 'pointer',
            'marginBottom': '5px'
        }),
        html.Div([
            html.P([
                html.Span('🔎 ', style={'marginRight': '4px'}),
                html.A('Search on Google',
                        href=f'https://www.google.com/search?q=CORDIS%20{title}',
                        target='_blank',
                        rel='noopener noreferrer',
                        style={'textDecoration': 'none','color': '#007BFF','fontWeight': 'bold'})
            ], style={'fontSize': '14px', 'marginTop': '10px'}),
            html.P(['🇪🇺 ', html.Span('Framework Programme: ', style={'fontWeight': 'bold'}), row['fp']]),
            html.P(['💡 ', html.Span('Topic: ', style={'fontWeight': 'bold'}), row['topic_name']]),
            html.P(['🏢 ', html.Span('Participants: ', style={'fontWeight': 'bold'}), ', '.join(row['participants'])]),
            html.Hr(),
            html.P(['📝 Abstract'], style={'fontWeight': 'bold'}),
            html.P(row['objective'], style={'fontSize': '14px', 'lineHeight': '1.5'})
        ], style={'padding': '10px', 'borderLeft': '2px solid #007BFF', 'marginLeft': '10px'})
    ], style={'marginBottom': '15px'})
'''


