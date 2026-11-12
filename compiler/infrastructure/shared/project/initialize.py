"""Create a minimal React/Express/SQLite workspace without replacing user files."""

from pathlib import Path
import json

from infrastructure.utils.files import save_json


DEFAULT_STACK = "react-express-sqlite"
BACKEND_TEST_SUPPORT = Path(__file__).with_name("support") / "backend_context.ts"

# --- Extension point: technology stacks --------------------------------------
# Register another template directory and its empty directories here. New
# database/backend stacks also need matching lowering adapters in steps 05/08.
STACKS = {
    DEFAULT_STACK: {
        "templates": Path(__file__).with_name("templates"),
        "directories": ("backend/src/db/tables", "backend/src/db/seeds"),
        "extra_files": {Path("backend/tests/support/context.ts"): BACKEND_TEST_SUPPORT},
        "build_directories": ("backend/dist", "frontend/dist"),
    },
}


def enable_import_case_checks(output_dir: Path, workspace: str) -> str:
    """Upgrade existing TypeScript projects to detect case-dependent module imports."""
    relative = f"{workspace}/tsconfig.json"
    path = output_dir / relative
    configuration = json.loads(path.read_text(encoding="utf-8-sig"))
    options = configuration.setdefault("compilerOptions", {})
    if options.get("forceConsistentCasingInFileNames") is not True:
        options["forceConsistentCasingInFileNames"] = True
        save_json(path, configuration)
    return relative


def initialize_project(output_dir: Path, stack: str = DEFAULT_STACK, port: int = 3000) -> list[str]:
    # Templates contain infrastructure only. Existing application sources and
    # data are preserved; dependencies are installed separately by the TDD step.
    """Copy missing files from the chosen stack template and return their workspace-relative paths; preserve existing files."""
    if stack not in STACKS:
        raise ValueError(f"Unknown technology stack: {stack}. Available: {', '.join(STACKS)}")
    if not 1 <= port <= 65535:
        raise ValueError("Backend port must be between 1 and 65535")
    configuration = STACKS[stack]
    output_dir = output_dir.resolve()
    templates = configuration["templates"]
    if not templates.is_dir():
        raise ValueError(f"Stack templates do not exist: {templates}")

    # copy template files to output directory, preserving existing application sources and data
    created = []
    sources = {source.relative_to(templates): source for source in templates.rglob("*") if source.is_file()}
    sources.update(configuration.get("extra_files", {}))
    for relative, source in sorted(sources.items()):
        content = source.read_text(encoding="utf-8-sig")

        # process port configuration in backend and frontend files
        if relative.as_posix() == "backend/src/server.ts":
            content = content.replace('process.env.PORT ?? "3000"', f'process.env.PORT ?? "{port}"')
        elif relative.as_posix() == "frontend/vite.config.ts":
            content = content.replace("http://127.0.0.1:3000", f"http://127.0.0.1:{port}")

        # write new files only; preserve existing application sources and data
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError:
            if not target.is_file():
                raise ValueError(f"Expected a project file: {target}")
            continue
        created.append(relative.as_posix())

    # create new directories
    for relative in configuration["directories"]:
        target = output_dir / relative
        target.mkdir(parents=True, exist_ok=True)
    return created
