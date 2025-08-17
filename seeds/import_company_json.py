# seeds/import_company_json.py
import json, sys, os
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()

from app.db import SessionLocal, engine
from app.models import Company, Base

DEFAULT_DURATION_MIN = 60  # podes ajustar por modalidade

def to_service(modalidade: dict, idx: int):
    code = modalidade.get("nome","service").lower().replace(" ", "_") + f"_{idx}"
    return {
        "code": code,
        "name": modalidade.get("nome"),
        "price": float(modalidade.get("preco") or 0.0),
        "duration_min": DEFAULT_DURATION_MIN,
        "schedule": modalidade.get("horarios", {}),
        "level": modalidade.get("nivel"),
        "description": modalidade.get("descricao"),
    }

# Garante que as tabelas existem
Base.metadata.create_all(bind=engine)

def run(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        # Mapear JSON → Company
        services = [to_service(m, i) for i, m in enumerate(data.get("modalidades", []))]
        business_hours = data.get("horario_funcionamento", {})
        address = data.get("localizacao", {}).get("endereco")
        company_key = data.get("empresa_id")
        company_name = data.get("nome_estudio")

        # ⚠️ Evita duplicado: tenta achar por key ou nome
        existing = None
        if company_key:
            existing = db.query(Company).filter(
                Company.brand_voice["company_key"].as_string() == str(company_key)
            ).first()
        if not existing and company_name:
            existing = db.query(Company).filter(Company.name == company_name).first()

        if existing:
            # Atualiza registo existente
            existing.business_hours = business_hours
            existing.address = address
            existing.phone_public = data.get("contato", {}).get("telefone")
            existing.email_public = data.get("contato", {}).get("email")
            existing.services = services
            bv = existing.brand_voice or {}
            bv.update({
                "company_key": company_key,
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
            })
            existing.brand_voice = bv
            db.commit()
            db.refresh(existing)
            print("Updated company id =", existing.id)
            print("Set EMPRESA_ID to this value in your envs.")
            return existing.id

        # Criar novo
        company = Company(
            name=company_name,
            locale="pt-PT",
            timezone="Europe/Lisbon",
            business_hours=business_hours,
            address=address,
            phone_public=data.get("contato", {}).get("telefone"),
            email_public=data.get("contato", {}).get("email"),
            services=services,
            brand_voice={
                "company_key": company_key,
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
    finally:
        db.close()

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "seeds/data/yoga_kula.json"
    run(path)
