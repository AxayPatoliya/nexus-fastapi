from __future__ import annotations
from pathlib import Path
import json
import re
from typing import Dict, List, Any, Optional
from datetime import datetime

DEFAULT_LAYOUT = {
    "app": ["routers", "models", "schemas", "crud"],
    "core": ["database", "config", "security"],
    "tests": [],
    "infra": []
}

class FastAPIGenerator:
    def __init__(self, project_name: str, config: Optional[Dict[str, Any]] = None, root: str | Path | None = None):
        self.project_name = project_name
        self.config = config or {
            "project_name": project_name,
            "description": "FastAPI application",
            "version": "1.0.0",
            "apps": []
        }
        self.base_path = Path(root).expanduser() if root is not None else Path(project_name)
        
    def create_directory_structure(self):
        """Create the basic directory structure"""
        directories = [
            self.base_path,
            self.base_path / "apps",
            self.base_path / "core",
            self.base_path / "core" / "database",
            self.base_path / "core" / "config",
            self.base_path / "core" / "security",
            self.base_path / "tests",
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            
        # Create __init__.py files
        init_files = [
            self.base_path / "__init__.py",
            self.base_path / "apps" / "__init__.py",
            self.base_path / "core" / "__init__.py",
            self.base_path / "core" / "database" / "__init__.py",
            self.base_path / "core" / "config" / "__init__.py",
            self.base_path / "core" / "security" / "__init__.py",
            self.base_path / "tests" / "__init__.py",
        ]
        
        for init_file in init_files:
            init_file.touch()

    def get_sqlalchemy_type(self, field_type: str) -> str:
        """Convert field type to SQLAlchemy type"""
        type_mapping = {
            'string': 'String',
            'integer': 'Integer',
            'float': 'Float',
            'boolean': 'Boolean',
            'datetime': 'DateTime',
            'text': 'Text',
            'json': 'JSON'
        }
        return type_mapping.get(field_type.lower(), 'String')

    def get_python_type(self, field_type: str) -> str:
        """Convert field type to Python type"""
        type_mapping = {
            'string': 'str',
            'integer': 'int',
            'float': 'float',
            'boolean': 'bool',
            'datetime': 'datetime',
            'text': 'str',
            'json': 'dict'
        }
        return type_mapping.get(field_type.lower(), 'str')

    def generate_model(self, app_name: str, model_config: Dict[str, Any]):
        """Generate SQLAlchemy model"""
        model_name = model_config['name']
        fields = model_config['fields']
        
        imports = {'Column', 'Integer'}
        imports.update(self.get_sqlalchemy_type(f['type']) for f in fields)
        model_content = f'''from sqlalchemy import {', '.join(sorted(imports))}
from core.database.base import Base
from datetime import datetime

class {model_name}(Base):
    __tablename__ = "{model_name.lower()}s"
    
    id = Column(Integer, primary_key=True, index=True)
'''
        
        for field in fields:
            field_name = field['name']
            field_type = self.get_sqlalchemy_type(field['type'])
            nullable = field.get('nullable', True)
            default = field.get('default')
            
            column_def = f"    {field_name} = Column({field_type}"
            
            if not nullable:
                column_def += ", nullable=False"
            
            if default is not None:
                if isinstance(default, str):
                    column_def += f', default="{default}"'
                else:
                    column_def += f', default={default}'
            
            column_def += ")\n"
            model_content += column_def
        
        return model_content

    def generate_schema(self, model_config: Dict[str, Any]):
        """Generate Pydantic schemas"""
        model_name = model_config['name']
        fields = model_config['fields']
        
        schema_content = '''from pydantic import BaseModel
from typing import Optional
from datetime import datetime

'''
        
        # Base schema
        schema_content += f'''class {model_name}Base(BaseModel):
'''
        for field in fields:
            field_name = field['name']
            field_type = self.get_python_type(field['type'])
            nullable = field.get('nullable', True)
            
            if nullable:
                schema_content += f"    {field_name}: Optional[{field_type}] = None\n"
            else:
                schema_content += f"    {field_name}: {field_type}\n"
        
        # Create schema
        schema_content += f'''

class {model_name}Create({model_name}Base):
    pass

class {model_name}Update({model_name}Base):
    pass

class {model_name}Response({model_name}Base):
    id: int
    
    class Config:
        from_attributes = True
'''
        
        return schema_content

    _ROUTE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

    def _model_labels(self, model_name: str) -> set[str]:
        base = model_name.lower()
        labels = {base}
        if base.endswith("s"):
            labels.add(base[:-1])
        else:
            labels.add(base + "s")
        return labels

    def _route_matches_model(self, route: Dict[str, Any], model_name: str) -> bool:
        explicit = route.get("model")
        if explicit:
            return str(explicit).lower() == model_name.lower()
        labels = self._model_labels(model_name)
        text = f"{route.get('name', '')} {route.get('path', '')}"
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        return bool(labels & tokens)

    def _uses_custom_routes(self, app_config: Dict[str, Any]) -> bool:
        return app_config.get("routes") is not None

    def _validate_app_routes(self, app_config: Dict[str, Any]) -> None:
        routes = app_config.get("routes")
        if routes is None:
            return
        app_name = app_config["name"]
        if not isinstance(routes, list):
            raise ValueError(f"App {app_name!r} routes must be a list.")
        models = app_config.get("models") or []
        if len(models) <= 1:
            if len(models) == 1:
                for route in routes:
                    explicit = route.get("model") if isinstance(route, dict) else None
                    if explicit and str(explicit).lower() != models[0]["name"].lower():
                        raise ValueError(
                            f"Route {route.get('name')!r} belongs to model {explicit!r}, "
                            f"which is not in app {app_name!r}."
                        )
            return
        for route in routes:
            if not isinstance(route, dict) or any(
                self._route_matches_model(route, model["name"]) for model in models
            ):
                continue
            raise ValueError(
                f"Route {route.get('name')!r} in app {app_name!r} does not match a model. "
                'Set "model" to the model name.'
            )

    def _normalize_route(self, app_name: str, route: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(route, dict):
            raise ValueError(f"Each route in app {app_name!r} must be an object.")
        name = route.get("name")
        method = str(route.get("method", "")).upper()
        path = route.get("path")
        if not name or path is None or path == "" or not method:
            raise ValueError(f"Each route in app {app_name!r} needs name, path, and method.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name)):
            raise ValueError(f"Route name {name!r} is not a valid Python identifier.")
        if method not in self._ROUTE_METHODS:
            raise ValueError(
                f"Route {name!r} has unsupported method {method!r}. "
                "Use GET, POST, PUT, PATCH, or DELETE."
            )
        if not str(path).startswith("/"):
            path = "/" + str(path)
        else:
            path = str(path)
        raw_params = re.findall(r"\{([^{}]+)\}", path)
        for param in raw_params:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", param):
                raise ValueError(f"Route {name!r} has invalid path parameter {param!r}.")
        kind = self._route_kind(name, method, raw_params)
        id_param = None
        if kind in {"get", "update", "delete"}:
            if "id" in raw_params:
                id_param = "id"
            elif raw_params:
                id_param = raw_params[0]
            else:
                raise ValueError(f"Route {name!r} needs a path parameter such as {{id}}.")
        return {
            "name": name,
            "method": method.lower(),
            "path": path,
            "kind": kind,
            "params": raw_params,
            "id_param": id_param,
        }

    def _route_kind(self, name: str, method: str, params: List[str]) -> str:
        if method == "POST":
            return "create"
        if method == "GET":
            return "get" if params else "list"
        if method in {"PUT", "PATCH"}:
            return "update"
        if method == "DELETE":
            return "delete"
        raise ValueError(f"Route {name!r} has unsupported method {method!r}.")

    def _default_routes(self, model_name: str) -> List[Dict[str, Any]]:
        model = model_name.lower()
        raw = [
            {"name": f"create_{model}", "path": "/", "method": "POST"},
            {"name": f"read_{model}s", "path": "/", "method": "GET"},
            {"name": f"read_{model}", "path": "/{id}", "method": "GET"},
            {"name": f"update_{model}", "path": "/{id}", "method": "PUT"},
            {"name": f"delete_{model}", "path": "/{id}", "method": "DELETE"},
        ]
        return [self._normalize_route(model, route) for route in raw]

    def _routes_for_model(self, app_config: Dict[str, Any], model_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Routes to generate for one model. Missing routes config means the full CRUD set."""
        model_name = model_config["name"]
        if not self._uses_custom_routes(app_config):
            return self._default_routes(model_name)
        models = app_config.get("models") or []
        if len(models) <= 1:
            chosen = app_config["routes"]
        else:
            chosen = [
                route for route in app_config["routes"]
                if self._route_matches_model(route, model_name)
            ]
        return [self._normalize_route(app_config["name"], route) for route in chosen]

    def generate_crud(self, model_config: Dict[str, Any], kinds: set[str]):
        """Generate CRUD operations for the selected route kinds."""
        model_name = model_config["name"]
        crud_kinds = set(kinds)
        if "update" in crud_kinds:
            crud_kinds.add("get")

        typing_imports = []
        if "list" in crud_kinds:
            typing_imports.append("List")
        if "get" in crud_kinds:
            typing_imports.append("Optional")
        schema_imports = []
        if "create" in crud_kinds:
            schema_imports.append(f"{model_name}Create")
        if "update" in crud_kinds:
            schema_imports.append(f"{model_name}Update")

        lines = ["from sqlalchemy.orm import Session"]
        if typing_imports:
            lines.append(f"from typing import {', '.join(typing_imports)}")
        lines.append(f"from .models import {model_name}")
        if schema_imports:
            lines.append(f"from .schemas import {', '.join(schema_imports)}")
        lines.append("")
        lines.append(f"class {model_name}CRUD:")

        methods = []
        if "create" in crud_kinds:
            methods.append(f'''    def create(self, db: Session, obj_in: {model_name}Create) -> {model_name}:
        db_obj = {model_name}(**obj_in.model_dump())
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj''')
        if "get" in crud_kinds:
            methods.append(f'''    def get(self, db: Session, id: int) -> Optional[{model_name}]:
        return db.query({model_name}).filter({model_name}.id == id).first()''')
        if "list" in crud_kinds:
            methods.append(f'''    def get_multi(self, db: Session, skip: int = 0, limit: int = 100) -> List[{model_name}]:
        return db.query({model_name}).offset(skip).limit(limit).all()''')
        if "update" in crud_kinds:
            methods.append(f'''    def update(self, db: Session, db_obj: {model_name}, obj_in: {model_name}Update) -> {model_name}:
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj''')
        if "delete" in crud_kinds:
            methods.append(f'''    def delete(self, db: Session, id: int) -> {model_name}:
        obj = db.query({model_name}).get(id)
        db.delete(obj)
        db.commit()
        return obj''')
        lines.append("\n\n".join(methods) if methods else "    pass")
        lines.append("")
        lines.append(f"{model_name.lower()}_crud = {model_name}CRUD()")
        return "\n".join(lines) + "\n"

    def generate_service(self, model_config: Dict[str, Any], kinds: set[str]):
        """Generate service methods for the selected route kinds."""
        model_name = model_config["name"]
        model_lower = model_name.lower()
        public = set(kinds)

        typing_imports = []
        if "list" in public:
            typing_imports.append("List")
        if public & {"get", "update", "delete"}:
            typing_imports.append("Optional")
        schema_imports = []
        if "create" in public:
            schema_imports.append(f"{model_name}Create")
        if "update" in public:
            schema_imports.append(f"{model_name}Update")
        if public:
            schema_imports.append(f"{model_name}Response")

        lines = ["from sqlalchemy.orm import Session"]
        if typing_imports:
            lines.append(f"from typing import {', '.join(typing_imports)}")
        lines.append(f"from .crud import {model_lower}_crud")
        if schema_imports:
            lines.append(f"from .schemas import {', '.join(schema_imports)}")
        lines.append("")
        lines.append(f"class {model_name}Service:")

        methods = []
        if "create" in public:
            methods.append(f'''    def create_{model_lower}(self, db: Session, obj_in: {model_name}Create) -> {model_name}Response:
        return {model_lower}_crud.create(db=db, obj_in=obj_in)''')
        if "get" in public:
            methods.append(f'''    def get_{model_lower}(self, db: Session, id: int) -> Optional[{model_name}Response]:
        return {model_lower}_crud.get(db=db, id=id)''')
        if "list" in public:
            methods.append(f'''    def get_{model_lower}s(self, db: Session, skip: int = 0, limit: int = 100) -> List[{model_name}Response]:
        return {model_lower}_crud.get_multi(db=db, skip=skip, limit=limit)''')
        if "update" in public:
            methods.append(f'''    def update_{model_lower}(self, db: Session, id: int, obj_in: {model_name}Update) -> Optional[{model_name}Response]:
        db_obj = {model_lower}_crud.get(db=db, id=id)
        if not db_obj:
            return None
        return {model_lower}_crud.update(db=db, db_obj=db_obj, obj_in=obj_in)''')
        if "delete" in public:
            methods.append(f'''    def delete_{model_lower}(self, db: Session, id: int) -> Optional[{model_name}Response]:
        return {model_lower}_crud.delete(db=db, id=id)''')
        lines.append("\n\n".join(methods) if methods else "    pass")
        lines.append("")
        lines.append(f"{model_lower}_service = {model_name}Service()")
        return "\n".join(lines) + "\n"

    def _route_function(self, model_name: str, route: Dict[str, Any]) -> str:
        model_lower = model_name.lower()
        kind = route["kind"]
        response_model = f"List[{model_name}Response]" if kind == "list" else f"{model_name}Response"
        args = [f"{param}: int" for param in route["params"]]
        if kind == "create":
            args.append(f"{model_lower}: {model_name}Create")
        elif kind == "update":
            args.append(f"{model_lower}: {model_name}Update")
        elif kind == "list":
            args.extend(["skip: int = 0", "limit: int = 100"])
        args.append("db: Session = Depends(get_db)")

        if kind == "create":
            body = f"    return {model_lower}_service.create_{model_lower}(db=db, obj_in={model_lower})"
        elif kind == "list":
            body = f"    return {model_lower}_service.get_{model_lower}s(db=db, skip=skip, limit=limit)"
        elif kind == "get":
            body = f'''    db_{model_lower} = {model_lower}_service.get_{model_lower}(db=db, id={route["id_param"]})
    if db_{model_lower} is None:
        raise HTTPException(status_code=404, detail="{model_name} not found")
    return db_{model_lower}'''
        elif kind == "update":
            body = f'''    db_{model_lower} = {model_lower}_service.update_{model_lower}(db=db, id={route["id_param"]}, obj_in={model_lower})
    if db_{model_lower} is None:
        raise HTTPException(status_code=404, detail="{model_name} not found")
    return db_{model_lower}'''
        else:
            body = f'''    db_{model_lower} = {model_lower}_service.delete_{model_lower}(db=db, id={route["id_param"]})
    if db_{model_lower} is None:
        raise HTTPException(status_code=404, detail="{model_name} not found")
    return db_{model_lower}'''

        return (
            f'@router.{route["method"]}("{route["path"]}", response_model={response_model})\n'
            f'def {route["name"]}({", ".join(args)}):\n'
            f"{body}\n"
        )

    def generate_routes(self, routed_models: List[tuple]):
        """Generate one router containing only the selected endpoints."""
        need_http = False
        need_list = False
        need_db = False
        schema_imports: List[str] = []
        service_imports: List[str] = []
        functions: List[str] = []

        for model_config, routes in routed_models:
            if not routes:
                continue
            need_db = True
            model_name = model_config["name"]
            service_imports.append(f"{model_name.lower()}_service")
            kinds = {route["kind"] for route in routes}
            if kinds & {"get", "update", "delete"}:
                need_http = True
            if "list" in kinds:
                need_list = True
            if "create" in kinds:
                schema_imports.append(f"{model_name}Create")
            if "update" in kinds:
                schema_imports.append(f"{model_name}Update")
            schema_imports.append(f"{model_name}Response")
            functions.extend(self._route_function(model_name, route) for route in routes)

        fastapi_imports = ["APIRouter"]
        if need_db:
            fastapi_imports.append("Depends")
        if need_http:
            fastapi_imports.append("HTTPException")

        lines = [f"from fastapi import {', '.join(fastapi_imports)}"]
        if need_db:
            lines.append("from sqlalchemy.orm import Session")
        if need_list:
            lines.append("from typing import List")
        if need_db:
            lines.append("from core.database.base import get_db")
        if schema_imports:
            lines.append(f"from .schemas import {', '.join(schema_imports)}")
        if service_imports:
            lines.append(f"from .service import {', '.join(service_imports)}")
        lines.append("")
        lines.append("router = APIRouter()")
        if functions:
            lines.append("")
            lines.append("\n".join(functions).rstrip())
        return "\n".join(lines) + "\n"

    def generate_app(self, app_config: Dict[str, Any]):
        """Generate a complete app with models, schemas, CRUD, and routes"""
        app_name = app_config['name']
        models = app_config['models']
        
        # Create app directory
        app_path = self.base_path / "apps" / app_name
        app_path.mkdir(parents=True, exist_ok=True)
        
        # Create __init__.py
        (app_path / "__init__.py").touch()
        
        # Generate models file
        models_content = ""
        for model in models:
            models_content += self.generate_model(app_name, model) + "\n\n"
        
        with open(app_path / "models.py", 'w') as f:
            f.write(models_content)
        
        # Generate schemas file
        schemas_content = ""
        for model in models:
            schemas_content += self.generate_schema(model) + "\n\n"
        
        with open(app_path / "schemas.py", 'w') as f:
            f.write(schemas_content)
        
        self._validate_app_routes(app_config)
        routed_models = []
        seen_names = set()
        for model in models:
            model_routes = self._routes_for_model(app_config, model)
            for route in model_routes:
                if route["name"] in seen_names:
                    raise ValueError(
                        f"Duplicate route name {route['name']!r} in app {app_name!r}."
                    )
                seen_names.add(route["name"])
            routed_models.append((model, model_routes))

        # Generate CRUD file
        crud_content = ""
        for model, model_routes in routed_models:
            kinds = {route["kind"] for route in model_routes}
            crud_content += self.generate_crud(model, kinds) + "\n\n"
        
        with open(app_path / "crud.py", 'w') as f:
            f.write(crud_content)
        
        # Generate service file
        service_content = ""
        for model, model_routes in routed_models:
            kinds = {route["kind"] for route in model_routes}
            service_content += self.generate_service(model, kinds) + "\n\n"
        
        with open(app_path / "service.py", 'w') as f:
            f.write(service_content)
        
        # Generate routes file
        with open(app_path / "routes.py", 'w') as f:
            f.write(self.generate_routes(routed_models))

    def generate_core_files(self):
        """Generate core configuration and database files"""
        
        # Settings file
        settings_content = '''from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Database settings
    DATABASE_URL: str = "sqlite:///./app.db"
    
    # Security settings
    SECRET_KEY: str = "your-secret-key-here"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"  # Allow extra fields

# Create settings instance
settings = Settings()

# Ensure database directory exists
db_path = settings.DATABASE_URL.replace('sqlite:///', '')
if db_path and not os.path.exists(os.path.dirname(db_path)):
    os.makedirs(os.path.dirname(db_path))
'''
        
        with open(self.base_path / "core" / "config" / "settings.py", 'w') as f:
            f.write(settings_content)
        
        # Database base file
        database_content = '''from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from core.config.settings import settings
import os

# Ensure the database directory exists
db_dir = os.path.dirname(settings.DATABASE_URL.replace('sqlite:///', ''))
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir)

# Create SQLite engine with proper configuration
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=True  # Enable SQL query logging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for models
Base = declarative_base()

def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''
        
        with open(self.base_path / "core" / "database" / "base.py", 'w') as f:
            f.write(database_content)
        
        # Requirements file
        requirements_content = '''nexus-fastapi>=0.1.0
'''
        
        with open(self.base_path / "requirements.txt", 'w') as f:
            f.write(requirements_content)
        
        # .env file
        env_content = '''DATABASE_URL=sqlite:///./app.db
SECRET_KEY=your-secret-key-here
'''
        
        with open(self.base_path / ".env", 'w') as f:
            f.write(env_content)

    def generate_main_app(self):
        """Generate the main FastAPI application file"""
        main_content = f'''from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config.settings import settings
from core.database.base import engine, Base

# Import all models to ensure they are registered with SQLAlchemy
'''
        
        # Add model imports
        for app in self.config.get('apps', []):
            app_name = app['name']
            for model in app['models']:
                model_name = model['name']
                main_content += f"from apps.{app_name}.models import {model_name}\n"
        
        main_content += '''
# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="{self.config['project_name']}",
    description="{self.config.get('description', 'FastAPI application')}",
    version="{self.config.get('version', '1.0.0')}"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers
'''
        
        # Add router imports and includes
        for app in self.config.get('apps', []):
            app_name = app['name']
            prefix = "/api" if self._uses_custom_routes(app) else f"/api/{app_name}"
            main_content += f"from apps.{app_name}.routes import router as {app_name}_router\n"
            main_content += f'app.include_router({app_name}_router, prefix="{prefix}", tags=["{app_name.title()}"])\n'
        
        main_content += '''
@app.get("/")
async def root():
    return {"message": "Welcome to FastAPI application"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
'''
        
        with open(self.base_path / "main.py", 'w') as f:
            f.write(main_content)

    def generate_project(self):
        """Generate the complete project"""
        print(f"Generating FastAPI project: {self.project_name}")
        
        # Create directory structure
        self.create_directory_structure()
        print("✓ Created directory structure")
        
        # Generate core files
        self.generate_core_files()
        print("✓ Generated core files")
        
        # Generate apps
        for app_config in self.config.get('apps', []):
            self.generate_app(app_config)
            print(f"✓ Generated app: {app_config['name']}")
        
        # Generate main application
        self.generate_main_app()
        print("✓ Generated main application")
        
        # Generate run script
        run_script = '''#!/usr/bin/env python3
import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
'''
        
        with open(self.base_path / "run.py", 'w') as f:
            f.write(run_script)
        
        print(f"\n🎉 Project '{self.project_name}' generated successfully!")
        print(f"\nTo run the project:")
        print(f"1. cd {self.project_name}")
        print(f"2. pip install -r requirements.txt")
        print(f"3. python run.py")
        print(f"\nAPI documentation will be available at: http://localhost:8000/docs")


def create_project(root: str | Path, template: str = "default", project_name: str = "service", config: Optional[Dict[str, Any]] = None):
    """Create a new FastAPI project with the specified template."""
    generator = FastAPIGenerator(project_name=project_name, config=config, root=root)
    generator.generate_project()
    return Path(root).expanduser().resolve()

def _load_template(name: str):
    raise NotImplementedError("Custom templates coming soon.")
