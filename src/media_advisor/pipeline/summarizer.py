"""AI-based summary generator for a single video.

Porting of src/pipeline/summarizer.ts.
"""

from media_advisor.models.claims import Claim

_SUMMARIZE_SYSTEM = """Sei un analista di media sportivi italiani.
Ti viene dato il testo di un video di commento calcistico e i claim principali estratti.
Produci un riassunto in italiano di 2-3 frasi che:
1. Descriva il tema centrale del video
2. Sintetizzi la posizione principale dell'autore
3. Menzioni eventuali ipotesi o conclusioni chiave
Max 150 parole, in italiano."""


async def generate_summary(
    api_key: str,
    model: str,
    title: str | None,
    author: str | None,
    full_text: str,
    claims: list[Claim],
) -> str:
    claims_text = "\n".join(
        f"- [{c.dimension}] {c.claim_text}" for c in claims[:8]
    )
    user_content = ""
    if title:
        user_content += f"Titolo: {title}\n"
    if author:
        user_content += f"Autore: {author}\n"
    user_content += f"\nTesto (estratto):\n{full_text[:3000]}\n\nClaim principali:\n{claims_text}"

    import openai

    client = openai.AsyncOpenAI(api_key=api_key)
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SUMMARIZE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        max_tokens=200,
        temperature=0.3,
    )
    return (completion.choices[0].message.content or "").strip()
