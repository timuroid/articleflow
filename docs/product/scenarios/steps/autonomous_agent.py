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

def repair_control(name):
    path=Path(__file__).resolve().parents[4]/'tests/test_repair034.py'
    spec=importlib.util.spec_from_file_location('repair034_contract_tests',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.RepairIsolationTests(name).run()
    assert result.wasSuccessful(),str(result.errors+result.failures)

@given('модель предлагает изменение защищённого компонента')
@given('кандидат проходит диагностический пример и проваливает закрытый')
def repair_setup(c):pass

@when('проверяется область разрешённого патча')
def protected_patch(c):repair_control('test_patch_cannot_edit_evaluator_or_escape_directory');c.checked=True

@when('агент получает обратную связь для следующего исправления')
def hidden_feedback(c):repair_control('test_sealed_failure_is_redacted_in_real_repair_loop_feedback');c.checked=True

@then('патч отклонён и исходный движок не изменён')
@then('содержимое закрытого примера остаётся скрытым и движок не принят')
def repair_checked(c):assert c.checked

def visual_control(name):
    path=Path(__file__).resolve().parents[4]/'tests/test_visual035.py'
    spec=importlib.util.spec_from_file_location('visual035_contract_tests',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.VisualTests(name).run()
    assert result.wasSuccessful(),str(result.errors+result.failures)

@given('агент задал необязательный вопрос')
@given('у результата отличается страница и отсутствует последняя')
def visual_setup(c):pass

@when('истекло окно ожидания ответа')
def timeout035(c):visual_control('test_timeout_is_not_consent');c.checked=True

@when('визуальная модель сообщает что всё нормально')
def wrong_vision035(c):visual_control('test_all_pages_missing_page_and_diagnosis_not_gate');c.checked=True

@then('агент продолжает без фиктивного согласия')
@then('несовпадения всех страниц сохраняются в проверке')
def visual_checked(c):assert c.checked
