"""Contract scenarios reuse executable synthetic integration controls."""
from behave import given,when,then
import importlib.util
from pathlib import Path

def control(name):
    path=Path(__file__).resolve().parents[4]/'tests/test_agent028.py'
    spec=importlib.util.spec_from_file_location('agent028_contract_tests',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    case=module.Agent028Tests(name)
    result=case.run()
    assert result.wasSuccessful(),str(result.errors+result.failures)

@given('синтетический эталон проходит обычное восстановление')
@given('агенту недоступны новые вызовы модели')
def setup(c):pass

@when('независимая стресс-проверка сообщает несовпадение')
def stress(c):control('test_stress_failure_prevents_certification_and_reaches_teacher_feedback');c.checked=True

@when('запрашивается автономное создание шаблона')
def limited(c):control('test_controller_stops_at_budget_and_does_not_certify');c.checked=True

@then('агент не выпускает шаблон и передаёт ошибку следующей итерации')
@then('сохраняется причина остановки без сертификации')
def verified(c):assert c.checked
