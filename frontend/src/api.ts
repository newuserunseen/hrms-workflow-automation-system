const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
export function token(){return localStorage.getItem("hrms_token")||""}
export async function api(path:string, options:RequestInit={}) {
  const headers:any={"Content-Type":"application/json",...(options.headers||{})};
  if(token()) headers.Authorization=`Bearer ${token()}`;
  const response=await fetch(`${BASE}${path}`,{...options,headers});
  const data=await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(data.detail||"Request failed");
  return data;
}
