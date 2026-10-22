import torch
import pandas as pd
from tqdm import tqdm
from FlagEmbedding import BGEM3FlagModel
from transformers import AutoTokenizer
from adapters import AutoAdapterModel


def build_corpus(df, sep_value='. '):
    
    def norm(col):
        return (df[col].fillna('').astype(str)
                .str.lower()
                .str.replace(r'\s+', ' ', regex=True)
                .str.strip())

    title = norm('title')
    objective = norm('objective')

    sep = pd.Series(sep_value, index=df.index).where((title != '') & (objective != ''), '')
    return (title + sep + objective).to_list()


def get_device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def extract_bgem3(df, device=None):
    """device: es. 'mps', 'cuda', 'cpu'; None lascia la scelta a FlagEmbedding."""
    corpus = build_corpus(df)

    kwargs = {'devices': str(device)} if device else {}
    model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True, **kwargs)

    all_embs = model.encode(
        corpus,
        batch_size=12,
        max_length=8192,
    )['dense_vecs']

    return all_embs


def extract_specter2(df, batch_size=32, device=None, progress=False):
    tokenizer = AutoTokenizer.from_pretrained('allenai/specter2_base')
    model = AutoAdapterModel.from_pretrained('allenai/specter2_base')
    model.load_adapter("allenai/specter2", source="hf", load_as="proximity", set_active=True)
    model.eval()

    device = torch.device(device) if device else get_device()
    model = model.to(device)

    corpus = build_corpus(df, sep_value=tokenizer.sep_token)

    all_embs = []
    with torch.no_grad(), tqdm(total=len(corpus), desc="SPECTER2", unit="projects",
                               disable=not progress) as pbar:
        for i in range(0, len(corpus), batch_size):
            batch = corpus[i:i + batch_size]
            inputs = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
                return_token_type_ids=False,
            ).to(device)

            output = model(**inputs)
            all_embs.append(output.last_hidden_state[:, 0, :].cpu())  # token [CLS]
            pbar.update(len(batch))

    all_embs = torch.cat(all_embs).numpy().astype('float32')

    return all_embs
