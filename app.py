import os
import bcrypt
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from supabase import create_client, Client

# --- CONFIGURATION ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERREUR: Variables d'environnement manquantes !")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Sereina API")

# --- MIDDLEWARE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODÈLES DE DONNÉES ---
class UserSignup(BaseModel):
    pseudo: str
    email: EmailStr
    password: str
    est_anonyme: bool = False
    pseudo_anonyme: str = None
    est_deprime: bool = False
from typing import Optional

class UserUpdate(BaseModel):
    pseudo: Optional[str] = None
    pseudo_anonyme: Optional[str] = None
    est_anonyme: Optional[bool] = None
    est_deprime: Optional[bool] = None
# Schema pour la connexion
class UserLogin(BaseModel):
    email: EmailStr
    password: str

# --- ROUTES ---

@app.get("/")
def read_root():
    return {"status": "Sereina API is running", "db_connected": SUPABASE_URL is not None}

@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(user: UserSignup):
    # 1. Vérification logique de l'anonymat
    if user.est_anonyme and not user.pseudo_anonyme:
        raise HTTPException(
            status_code=400, 
            detail="Un pseudo anonyme est requis pour le mode anonyme."
        )

    # 2. Hachage du mot de passe avec bcrypt (Version corrigée pour Python 3.12)
    try:
        # On encode le mot de passe en bytes, on génère un sel et on hache
        password_bytes = user.password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    except Exception as e:
        print(f" Erreur hachage: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la sécurisation du mot de passe.")

    # 3. Préparation des données pour Supabase
    user_data = {
        "pseudo": user.pseudo,
        "email": user.email.lower(),
        "password": hashed_password,
        "est_anonyme": user.est_anonyme,
        "pseudo_anonyme": user.pseudo_anonyme if user.est_anonyme else None,
        "est_deprime": user.est_deprime
    }

    try:
        # 4. Insertion dans Supabase
        response = supabase.table("utilisateurs").insert(user_data).execute()
        
        # Vérification du retour
        if not response.data:
            raise HTTPException(status_code=500, detail="Échec de l'enregistrement.")

        user_created = response.data[0]
        
        # Sécurité : On ne renvoie jamais le password au front
        if "password" in user_created:
            del user_created["password"]

        return {
            "status": "success",
            "message": "Utilisateur créé avec succès",
            "user": user_created
        }

    except Exception as e:
        error_msg = str(e)
        print(f"🔥 Erreur Supabase: {error_msg}")
        
        if "duplicate key" in error_msg.lower():
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé.")
        
        # Pour le débuggage en remote, on renvoie l'erreur détaillée
        raise HTTPException(status_code=500, detail=f"Erreur base de données: {error_msg}")
# --- ROUTE : MODIFICATION DU PROFIL ---
@app.put("/api/user/update/{user_id}")
async def update_profile(user_id: str, data: UserUpdate):
    """
    Met à jour les informations d'un utilisateur existant via son ID.
    """
    # On filtre les champs envoyés pour ne garder que ceux qui ne sont pas None
    data_to_update = {k: v for k, v in data.dict().items() if v is not None}
    
    if not data_to_update:
        raise HTTPException(status_code=400, detail="Aucune donnée fournie pour la modification.")

    try:
        # Mise à jour dans Supabase avec filtre sur l'id_user
        response = supabase.table("user").update(data_to_update).eq("id_user", user_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")

        updated_user = response.data[0]
        # On s'assure de ne pas renvoyer le mot de passe s'il était présent
        if "password" in updated_user:
            del updated_user["password"]

        return {"status": "success", "message": "Profil mis à jour", "user": updated_user}

    except Exception as e:
        print(f"Erreur Update: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# Suppression de compte
@app.delete("/api/user/delete/{user_id}")
async def delete_user(user_id: str):
    try:
        response = supabase.table("user").delete().eq("id_user", user_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="ID introuvable")

        return {"status": "success", "message": "Compte supprime"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Echec de la suppression")

# --- ROUTE : CONNEXION (LOGIN) ---
@app.post("/api/auth/login")
async def login(credentials: UserLogin):
    try:
        # Recuperation de l'utilisateur par email
        response = supabase.table("user").select("*").eq("email", credentials.email.lower()).execute()
        
        if not response.data:
            raise HTTPException(status_code=401, detail="Identifiants incorrects")

        user_info = response.data[0]

        # Verification du mot de passe hache
        password_bytes = credentials.password.encode('utf-8')
        hashed_bytes = user_info["password"].encode('utf-8')

        if not bcrypt.checkpw(password_bytes, hashed_bytes):
            raise HTTPException(status_code=401, detail="Identifiants incorrects")

        # Nettoyage des donnees sensibles avant retour
        user_info.pop("password", None)

        return {
            "status": "success",
            "message": "Connexion reussie",
            "user": user_info
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erreur Login: {str(e)}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'authentification")

# --- ROUTE : DECONNEXION (LOGOUT) ---
@app.post("/api/auth/logout")
async def logout():
    """
    Cote API, le logout est simple car on ne stocke pas de session.
    Le frontend devra vider son cache/localStorage.
    """
    return {"status": "success", "message": "Deconnecte avec succes"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)