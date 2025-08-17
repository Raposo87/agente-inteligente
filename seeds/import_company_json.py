# seeds/import_company_json.py
import json, sys
from datetime import timedelta
from app.db import SessionLocal
from app.models import Company

DEFAULT_DURATION_MIN = 60  # podes ajustar por modalidade, se quiseres

def to_service(modalidade: dict, idx: int):
    code = modalidade.get("nome","service").lower().replace(" ", "_") + f"_{idx}"
    return {
        "code": code,
        "name": modalidade.get("nome"),
        "price": float(modalidade.get("preco") or 0.0),
        "duration_min": DEFAULT_DURATION_MIN,
        # guardamos horários específicos no serviço (útil para mensagens)
        "schedule": modalidade.get("horarios", {}),
        "level": modalidade.get("nivel"),
        "description": modalidade.get("descricao"),
    }

def run(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()

    # Mapear JSON → Company
    services = [to_service(m, i) for i, m in enumerate(data.get("modalidades", []))]
    business_hours = data.get("horario_funcionamento", {})

    address = data.get("localizacao", {}).get("endereco")
    company = Company(
        name=data.get("nome_estudio"),
        locale="pt-PT",
        timezone="Europe/Lisbon",
        business_hours=business_hours,
        address=address,
        phone_public=data.get("contato", {}).get("telefone"),
        email_public=data.get("contato", {}).get("email"),
        services=services,
        brand_voice={
            "company_key": data.get("empresa_id"),
            "site_url": data.get("site_url"),
            "description": data.get("descricao"),
            "neighborhood": data.get("localizacao", {}).get("bairro"),
            "city": data.get("localizacao", {}).get("cidade"),
            "country": data.get("localizacao", {}).get("pais"),
            "pricing": data.get("precos"),
            "discounts": data.get("descontos"),
            "faq": data.get("faq"),
            "teachers": data.get("professoras"),
            "lotacao_por_aula": data.get("lotacao_por_aula"),
        },
    )

    db.add(company)
    db.commit()
    db.refresh(company)

    print("Imported company id =", company.id)
    print("Set EMPRESA_ID to this value in your envs.")
    return company.id

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "seeds/data/yoga_kula.json"
    run(path)
