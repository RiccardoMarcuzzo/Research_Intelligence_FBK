import re

def format_name(text, lowercase_stopwords):
    text = text.lower()
    text = re.sub(r'[""\'«»„“]', '', text)
    words = text.split()
    if not words:
        return ""
    processed_words = []

    for i, word in enumerate(words):
        # La prima parola di una stringa va sempre maiuscola
        if i == 0:
            processed_words.append(word.capitalize())
        # Se la parola è nella lista delle "piccole", resta minuscola
        elif word.lower() in lowercase_stopwords:
            processed_words.append(word.lower())
        # Altrimenti Camel Case (Capitalize)
        else:
            processed_words.append(word.capitalize())

    return " ".join(processed_words)