import os
import bcrypt
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from supabase import create_client, Client
import jwt
from datetime import datetime, timedelta
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
SECRET_KEY = "votre_cle_secrete_eni_sereina_2026" 
ALGORITHM = "HS256"
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
        print(f"Erreur Supabase: {error_msg}")
        
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
        # 1. On cherche l'utilisateur dans la table 'utilisateurs' (vue sur ton screenshot)
        # On utilise .lower() pour éviter les erreurs de majuscules dans l'email
        query = supabase.table("utilisateurs").select("*").eq("email", credentials.email.lower()).execute()
        
        # 2. Si l'utilisateur n'existe pas
        if not query.data:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

        user_info = query.data[0]

        # 3. Vérification du mot de passe avec bcrypt
        # On compare le mot de passe reçu avec le hash stocké en base
        password_byte = credentials.password.encode('utf-8')
        stored_hash_byte = user_info["password"].encode('utf-8')

        if not bcrypt.checkpw(password_byte, stored_hash_byte):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

        # 4. GÉNÉRATION DU TOKEN 
        expire = datetime.utcnow() + timedelta(days=30)
        
        # Le 'payload' contient les infos que React pourra lire (sans le mot de passe !)
        payload = {
            "user_id": str(user_info.get("id_user") or user_info.get("id")), # Sécurité si id ou id_user
            "email": user_info["email"],
            "exp": int(expire.timestamp()) # Conversion en timestamp pour JWT
        }
        
        token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

        
        user_data = {
            "id_user": user_info["id_user"],
            "pseudo": user_info.get("pseudo"),
            "est_anonyme": user_info.get("est_anonyme"),
            "pseudo_anonyme": user_info.get("pseudo_anonyme")
        }

        # 6. RÉPONSE FINALE
        return {
            "status": "success",
            "message": "Connexion réussie",
            "token": token, 
            "user": user_data
        }

    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        # On affiche l'erreur dans tes logs Render pour le debug
        print(f"ERREUR LOGIN : {str(e)}")
        raise HTTPException(status_code=500, detail="Une erreur interne est survenue")
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