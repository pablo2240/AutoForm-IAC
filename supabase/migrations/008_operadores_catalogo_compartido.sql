-- ADR-0014: catálogo compartido de diligenciadores ("Diligenciado por").
-- Cualquier usuario activo puede crear diligenciadores y editar los que no
-- pertenecen a una cuenta; borrar sigue siendo exclusivo de administradores.
-- Migración aditiva: solo reemplaza políticas RLS de public.operadores.

DROP POLICY IF EXISTS "operadores_insert_admin" ON public.operadores;
DROP POLICY IF EXISTS "operadores_insert_activo" ON public.operadores;
CREATE POLICY "operadores_insert_activo"
    ON public.operadores FOR INSERT TO authenticated
    WITH CHECK (
        public.is_admin()
        OR (public.is_active_user() AND usuario_id IS NULL AND es_activo = false)
    );

DROP POLICY IF EXISTS "operadores_update_dueno_o_admin" ON public.operadores;
DROP POLICY IF EXISTS "operadores_update_activo" ON public.operadores;
CREATE POLICY "operadores_update_activo"
    ON public.operadores FOR UPDATE TO authenticated
    USING (
        public.is_admin()
        OR (public.is_active_user() AND (usuario_id IS NULL OR usuario_id = auth.uid()))
    )
    WITH CHECK (
        public.is_admin()
        OR (public.is_active_user() AND (usuario_id IS NULL OR usuario_id = auth.uid()))
    );

-- operadores_select_auth y operadores_delete_admin se mantienen sin cambios.
