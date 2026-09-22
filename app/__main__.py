from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .agentdojo import import_export
from .config import settings
from .database import Database
from .evaluation import evaluation_json
from .fine_tuning import export_dataset
from .reviewer import ReviewerTrainer, load_latest_reviewer
from .seed import seed


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="approval-reviewer")
    command_parser.add_argument("--database", type=Path, default=settings.database_path)
    commands = command_parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the local database")
    commands.add_parser("seed", help="Add the local demo workspace and transparent curated fixtures")
    serve = commands.add_parser("serve", help="Run the local review interface")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("train", help="Train a versioned local reviewer from reviewed examples")
    commands.add_parser("evaluate", help="Evaluate rules and reviewer versions on held-out examples")
    commands.add_parser("export-finetune", help="Build a versioned fine-tuning JSONL package")
    import_command = commands.add_parser("import-agentdojo", help="Import a saved local AgentDojo export")
    import_command.add_argument("input", type=Path)
    mode = commands.add_parser("set-mode", help="Choose how eligible actions are handled")
    mode.add_argument("mode", choices=("human", "rules", "learned"))
    return command_parser


def main() -> None:
    arguments = parser().parse_args()
    local_settings = replace(settings, database_path=arguments.database)
    database = Database(local_settings.database_path)
    database.initialize()

    if arguments.command == "init":
        print(f"Initialized {local_settings.database_path}")
        return
    if arguments.command == "seed":
        report = seed(database)
        print(f"Seeded {report['documents']} documents, {report['permissions']} permissions, and {report['fixtures']} curated fixtures")
        return
    if arguments.command == "train":
        report = ReviewerTrainer(database, local_settings.model_directory).train()
        print(f"Trained {report['version']} on {report['training_count']} examples with threshold {report['threshold']}")
        return
    if arguments.command == "evaluate":
        print(evaluation_json(database))
        return
    if arguments.command == "export-finetune":
        report = export_dataset(database, local_settings.artifact_directory)
        print(
            f"Exported {report['version']} with {report['train_examples']} training and "
            f"{report['validation_examples']} validation examples"
        )
        return
    if arguments.command == "import-agentdojo":
        print(f"Imported {import_export(database, arguments.input)} owner-curated exported examples")
        return
    if arguments.command == "set-mode":
        if arguments.mode == "learned" and not load_latest_reviewer(database):
            raise SystemExit("No trained local reviewer is available. Run train first.")
        database.set_setting("reviewer_mode", arguments.mode)
        print(f"Reviewer mode is now {arguments.mode}")
        return
    if arguments.command == "serve":
        try:
            import uvicorn
        except ImportError as error:
            raise SystemExit("Install project dependencies before running the interface") from error
        from .web import create_app

        uvicorn.run(create_app(local_settings), host=arguments.host, port=arguments.port)


if __name__ == "__main__":
    main()
