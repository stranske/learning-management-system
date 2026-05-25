# CSV Graph Import Format

`lms import-graph <path>` seeds draft knowledge graph records from a CSV file.
The importer validates the full file before writing anything, so unknown
prerequisite references fail without partial graph changes.

## Columns

Required columns:

- `title`: unique node title within the `ownership_scope`.
- `knowledge_type`: one of the graph model knowledge types, such as `factual`,
  `conceptual`, or `procedural`.
- `prerequisites`: prerequisite node titles in the same ownership scope, separated
  by `|` or `;`. Leave blank when the node has no prerequisite.
- `ownership_scope`: `personal` or `institutional`.
- `status`: normally `draft` for imported graph bootstrap data.
- `source_locator`: stable locator for the source outline, spreadsheet, or note.

Optional columns:

- `source_range`: row, sheet, or passage locator inside the source.
- `description`: node description.

## Example

```csv
title,knowledge_type,prerequisites,ownership_scope,status,source_locator,source_range,description
Probability Basics,conceptual,,personal,draft,course-outline.csv,row 2,Core probability vocabulary
Bayes Rule,procedural,Probability Basics,personal,draft,course-outline.csv,row 3,Use prior and conditional probabilities
Posterior Checks,judgment,Probability Basics|Bayes Rule,personal,draft,course-outline.csv,row 4,Assess posterior reasonableness
```

Dry run:

```bash
lms import-graph course-outline.csv --dry-run
```

Output includes node, edge, and source-reference counts before any writes.

