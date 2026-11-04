import { cp } from "node:fs/promises";

// SQL stays in separate files and is copied beside the compiled DB modules.
for (const directory of ["tables", "seeds"]) {
  await cp(new URL(`../src/db/${directory}/`, import.meta.url), new URL(`../dist/db/${directory}/`, import.meta.url), { recursive: true });
}
