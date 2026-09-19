import asyncio

from app.orchestrator.runner import ExperimentRunner
from app.schemas.experiment import ExperimentConfig


def _drive(config: ExperimentConfig, speed: float) -> list:
    async def run() -> list:
        runner = ExperimentRunner(config)
        runner.tick_interval = 0
        runner.set_speed(speed)
        await runner.publish_initial()
        await runner._run_loop()
        events = runner.bus.since(-1)
        return [
            (
                e.seq,
                e.sim_tick,
                e.event_type,
                e.agent_id,
                e.source_agent_id,
                e.target_agent_id,
                e.metadata,
            )
            for e in events
        ]

    return asyncio.run(run())


def test_speed_does_not_affect_event_projection():
    config = ExperimentConfig(seed=42, node_count=25, max_ticks=10)
    assert _drive(config, 1.0) == _drive(config, 8.0) == _drive(config, 0.25)


async def _with_pause_resume(config: ExperimentConfig) -> list:
    runner = ExperimentRunner(config)
    runner.tick_interval = 0
    await runner.publish_initial()
    task = asyncio.create_task(runner._run_loop())

    await asyncio.sleep(0)
    runner.pause()
    frozen_tick = runner.state.tick
    for _ in range(5):
        await asyncio.sleep(0)
        assert runner.state.tick == frozen_tick

    runner.resume()
    await task
    events = runner.bus.since(-1)
    return [
        (
            e.seq,
            e.sim_tick,
            e.event_type,
            e.agent_id,
            e.source_agent_id,
            e.target_agent_id,
            e.metadata,
        )
        for e in events
    ]


def test_pause_resume_does_not_perturb_event_projection():
    config = ExperimentConfig(seed=42, node_count=25, max_ticks=10)
    assert _drive(config, 1.0) == asyncio.run(_with_pause_resume(config))
