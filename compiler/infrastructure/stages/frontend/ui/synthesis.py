"""Step 07 orchestration: retrieve pages, propose UI/data, parse, and publish.

All leaf requirements are designed before step 08 implements any UI. Reuse is
page-first: retrieval returns the corresponding UI/data subtree, not disconnected
components. Prompts and design records live in ui/design.py."""

from infrastructure.stages.frontend.ui.design import INSTRUCTIONS, apply_proposal, empty_design, normalize_design, UIResponseError, data_symbols
from infrastructure.stages.frontend.ui.proposals import INSTRUCTIONS as EXAMPLE_INSTRUCTIONS
from infrastructure.shared.rag.pages import PageRetriever
from infrastructure.utils.files import save_json
from infrastructure.shared.agent.design_batches import DesignBatches, exact_keys, check_shared_records
from infrastructure.shared.agent.discovery import ContextIndex


def bind_requirement_image_pages(design, requirement, rid):
    """Bind image-backed pages to the current requirement when the page hint is unambiguous."""
    owned = list(design["requirements"].get(rid, []))
    images = requirement.get("images", {})
    image_records = images.values() if isinstance(images, dict) else images
    for image in image_records:
        if not isinstance(image, dict):
            continue
        image_id, page_hint = image.get("id"), image.get("page")
        # The requirement's explicit page hint is authoritative. The model may
        # omit the redundant page.images entry when creating a new page.
        if page_hint in design["pages"]:
            page = design["pages"][page_hint]
            page.setdefault("images", [])
            if image_id not in page["images"]:
                page["images"].append(image_id)
            candidates = [page_hint]
        else:
            candidates = [pid for pid, page in design["pages"].items() if image_id in page.get("images", [])]
        if len(candidates) != 1:
            continue
        root = design["pages"][candidates[0]]["root"]
        if root in design["elements"]:
            if root not in owned:
                owned.append(root)
    design["requirements"][rid] = owned


def synthesize_ui(arc_dir, tree, images, contexts, model, console, top_k=3, max_attempts=10):
    """Design UI/data by batch and apply existing per-leaf checks before saving."""
    design, retriever = empty_design(), PageRetriever()
    for rid in tree.requirements:
        if tree.children[rid]:
            design["requirements"][rid] = []
            for sid in tree.own_steps[rid]:
                design["steps"][sid] = []
    path = arc_dir / "ui_design.json"
    batches = DesignBatches(arc_dir, "07_design_ui", console)

    def process(batch):
        nonlocal design
        requests, pages = {}, {}
        for rid in batch.leaves:
            requirement = contexts[rid]
            retrieved = retriever.retrieve(requirement, design, top_k)
            pages.update(retrieved["pages"])
            requests[rid] = {"images": requirement["images"], "candidate_pages": list(retrieved["pages"])}

        def accept(proposal):
            entries = proposal["requirements"]
            candidate = design
            check_shared_records(entries, ("pages", "elements"))
            for rid in batch.leaves:
                entry = entries[rid]
                try:
                    exact_keys(entry["step_ui"], tree.own_steps[rid], f"{rid} steps")
                    candidate = apply_proposal(candidate, entry, rid, tree)
                except (KeyError, TypeError, AttributeError) as error:
                    raise UIResponseError(error, entry) from error
            for rid in batch.leaves:
                bind_requirement_image_pages(candidate, contexts[rid], rid)
            return normalize_design(candidate, tree)

        design = batches.propose(batch, model, INSTRUCTIONS + "\n\n" + EXAMPLE_INSTRUCTIONS,
            requests, accept, max_attempts, shared={"retrieved_pages": pages},
            context_index=ContextIndex(lambda: {"page": design["pages"], "ui_element": design["elements"],
                "ui_data": data_symbols(design["elements"])}))
        save_json(path, design)
        console.artifact("ui_design", design, batch.id + " | Accepted UI")
        return True

    batches.run(process)
    return design
