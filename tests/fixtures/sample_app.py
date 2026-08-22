from fastapi import APIRouter, Depends

router = APIRouter()


class Output:
    pass


class Source:
    pass


def get_source() -> Source:
    return Source()


# code-steward: unit taxonomy.normalize
def normalize_taxon_name(name: str, source: Source) -> Output:
    """Normalize a taxon name and resolve aliases."""
    return Output()


# code-steward: begin taxonomy.validation


def validate_name(name: str) -> bool:
    return bool(name.strip())


def validate_source(source: Source) -> bool:
    return source is not None


# code-steward: end taxonomy.validation


# code-steward: unit organisms.create
@router.post("/organisms", response_model=Output)
async def create_organism(name: str, source: Source = Depends(get_source)) -> Output:
    """Create an organism."""
    return normalize_taxon_name(name, source)
