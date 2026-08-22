from fastapi import APIRouter, Depends

router = APIRouter()


class Output:
    pass


class Source:
    pass


def get_source() -> Source:
    return Source()


# <code-unit:taxonomy.normalize>
# @purpose Normalize species names and resolve aliases.
# @owns taxonomy normalization, alias resolution
# @concepts taxonomy, species, aliases

def normalize_taxon_name(name: str, source: Source) -> Output:
    """Normalize a taxon name and resolve aliases."""
    return Output()


# </code-unit:taxonomy.normalize>


@router.post("/organisms", response_model=Output)
async def create_organism(name: str, source: Source = Depends(get_source)) -> Output:
    """Create an organism."""
    return normalize_taxon_name(name, source)
