import json, sys
from app.db import SessionLocal
from app.models import Company

def run(path):
    db = SessionLocal()
    data = json.load(open(path))
    c = Company(
        name=data['name'],
        locale=data.get('locale','pt-PT'),
        timezone=data.get('timezone','Europe/Lisbon'),
        brand_voice=data.get('brand_voice',{}),
        business_hours=data.get('business_hours',{}),
        address=data.get('address'),
        phone_public=data.get('phone'),
        email_public=data.get('email'),
        services=data.get('services',[])
    )
    db.add(c); db.commit()
    print('Imported company id=', c.id)

if __name__ == '__main__':
    run(sys.argv[1])