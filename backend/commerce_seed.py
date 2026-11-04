"""Repeatable insert-only synthetic catalogs; never overwrites existing catalog terms."""
from decimal import Decimal
from sqlalchemy.dialects.postgresql import insert
from commerce_models import DemoOperator, RechargePlan, DemoBiller


def seed(connection):
    operators = [("payflow-mobile", "PayFlow Mobile"), ("novatel", "NovaTel Demo"), ("bluewave", "BlueWave Telecom Demo")]
    for code, name in operators:
        connection.execute(insert(DemoOperator).values(id=code, name=name).on_conflict_do_nothing())
        for price, label, days in [(99, "Starter", 7), (199, "Basic", 28), (299, "Plus", 28), (599, "Premium", 84)]:
            connection.execute(insert(RechargePlan).values(id=f"{code}-{price}", operator_id=code,
                name=f"Demo {label}", price=Decimal(price), validity_days=days,
                description="Fictional 1 GB/day and unlimited demo voice. No service is activated.").on_conflict_do_nothing())
    for code, name, category in [("electric", "PayFlow Electric Demo", "Electricity"), ("water", "ClearWater Utilities Demo", "Water"),
        ("gas", "HomeGas Demo", "Gas"), ("broadband", "FiberConnect Demo", "Broadband")]:
        connection.execute(insert(DemoBiller).values(id=code, name=name, category=category,
            description="Synthetic monthly bills only. No connection to a utility provider.").on_conflict_do_nothing())


if __name__ == "__main__":
    from database import engine
    with engine.begin() as connection:
        seed(connection)
    print("Demo catalogs seeded without replacing existing records.")
