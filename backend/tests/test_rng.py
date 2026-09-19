from app.engine.rng import rng


def test_same_key_same_value():
    a = rng(42, 3, "agent-000", "infect:agent-001").random()
    b = rng(42, 3, "agent-000", "infect:agent-001").random()
    assert a == b


def test_different_keys_different_streams():
    values = {
        rng(42, 0, "agent-000", "infect:agent-001").random(),
        rng(42, 1, "agent-000", "infect:agent-001").random(),
        rng(42, 0, "agent-001", "infect:agent-001").random(),
        rng(42, 0, "agent-000", "infect:agent-002").random(),
        rng(43, 0, "agent-000", "infect:agent-001").random(),
    }
    assert len(values) == 5


def test_independent_of_call_order():
    keys = [
        (42, 0, "agent-000", "infect:agent-001"),
        (42, 1, "agent-002", "infect:agent-003"),
        (42, 2, "agent-004", "infect:agent-000"),
    ]
    forward = [rng(*k).random() for k in keys]
    backward = [rng(*k).random() for k in reversed(keys)]
    assert forward == list(reversed(backward))


def test_returns_fresh_generator_each_call():
    r1 = rng(42, 0, "agent-000", "infect:agent-001")
    r2 = rng(42, 0, "agent-000", "infect:agent-001")
    assert r1 is not r2
