from fastapi import Header, HTTPException, status

def require_admin(x_admin_token: str = Header(default="admin-token")):
    if x_admin_token != "admin-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )
    return {"user": "admin"}


def get_current_user(x_user_id: str = Header(default="default-user")):
    return x_user_id
