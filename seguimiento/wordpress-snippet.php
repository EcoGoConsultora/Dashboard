<?php
/**
 * Eco Go — Tablero de clientes con registro de uso (snippet de WordPress)
 *
 * Arma el iframe del tablero de clientes pasándole el ID del usuario que
 * inició sesión (index-clientes.html?u=<ID>), así el tablero puede anotar qué
 * hace cada cliente. Además manda nombre, email y empresa del usuario a la
 * planilla (pestaña Usuarios), de servidor a servidor: el mail nunca pasa por
 * el navegador ni por la URL.
 *
 * Dónde va: plugin "Code Snippets" (snippet PHP, "Ejecutar en todas partes";
 * ahí se pega sin la línea <?php de arriba) o functions.php del tema hijo.
 * En la página de clientes se reemplaza el iframe actual por el shortcode
 * [ecogo_tablero_clientes]. Ver SEGUIMIENTO.md.
 */

add_shortcode('ecogo_tablero_clientes', function () {
    // URL de la aplicación web del Apps Script (termina en /exec) y la clave
    // que muestra configurar(). La clave se completa solo acá, nunca en GitHub.
    $registro_url   = 'https://script.google.com/a/macros/ecogo.com.ar/s/AKfycbzYg6x057Hlhu0LixCIK9IvPnlnDZ07-VTrmCZ--MPe-RfIH10OprGQpdKr3xJAG2KA-w/exec';
    $registro_clave = 'PEGAR-CLAVE';
    $src = 'https://ecogoconsultora.github.io/Dashboard/index-clientes.html';

    $user = wp_get_current_user();
    if ($user->ID) {
        $src = add_query_arg('u', $user->ID, $src);

        // Avisa a la planilla quién es el usuario. Como mucho una vez cada 12
        // horas por usuario, para no demorar la página en cada visita.
        $ultimo = (int) get_user_meta($user->ID, 'ecogo_registro_sync', true);
        if (time() - $ultimo > 12 * HOUR_IN_SECONDS) {
            $r = wp_remote_post($registro_url, array(
                'timeout' => 4,
                'headers' => array('Content-Type' => 'text/plain; charset=utf-8'),
                'body'    => wp_json_encode(array(
                    'tipo'    => 'usuario',
                    'clave'   => $registro_clave,
                    'u'       => $user->ID,
                    'nombre'  => $user->display_name,
                    'email'   => $user->user_email,
                    'empresa' => get_user_meta($user->ID, 'billing_company', true),
                    'alta'    => $user->user_registered,
                )),
            ));
            if (!is_wp_error($r)) update_user_meta($user->ID, 'ecogo_registro_sync', time());
        }
    }

    return '<iframe src="' . esc_url($src) . '" title="Dashboard Eco Go clientes"'
         . ' width="100%" height="900px" style="border:0"></iframe>';
});
