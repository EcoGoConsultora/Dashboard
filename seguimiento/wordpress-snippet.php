<?php
/**
 * Eco Go — Registro de uso del tablero (snippet de WordPress)
 *
 * Con un usuario logueado hace dos cosas:
 * 1. Le agrega ?u=<ID de WordPress> a los iframes y links del tablero
 *    (ecogoconsultora.github.io/Dashboard/...) de la página que se muestra,
 *    así el tablero sabe quién es. No hay que tocar las entradas: el iframe
 *    vive en un campo de JetEngine que muestra la plantilla de Elementor, y
 *    esto lo agarra esté donde esté.
 * 2. Le manda a la planilla nombre, email y empresa del usuario, de servidor
 *    a servidor: el mail nunca pasa por el navegador ni por la URL.
 *
 * Dónde va: plugin "Code Snippets" (snippet PHP, "Ejecutar el fragmento en
 * todas partes"; ahí se pega sin la línea <?php de arriba). Ver SEGUIMIENTO.md.
 */

add_action('template_redirect', function () {
    if (!is_user_logged_in()) return;

    // URL de la aplicación web del Apps Script (termina en /exec) y la clave
    // que muestra configurar(). La clave se completa solo acá, nunca en GitHub.
    $registro_url   = 'https://script.google.com/a/macros/ecogo.com.ar/s/AKfycbzYg6x057Hlhu0LixCIK9IvPnlnDZ07-VTrmCZ--MPe-RfIH10OprGQpdKr3xJAG2KA-w/exec';
    $registro_clave = 'PEGAR_CLAVE_ACA';

    $user = wp_get_current_user();

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

    // Agrega ?u=<ID> a las URLs del tablero (páginas .html o la raíz; no a
    // los archivos de estilos o datos). Si ya tienen u=, no las toca.
    ob_start(function ($html) use ($user) {
        return preg_replace_callback(
            '~(ecogoconsultora\.github\.io/Dashboard/(?:[\w./-]*\.html)?)(\?[^"\'\s<>#]*)?(?=["\'\s<>#])~',
            function ($m) use ($user) {
                $q = isset($m[2]) ? $m[2] : '';
                if (preg_match('/[?&]u=/', $q)) return $m[0];
                return $m[1] . ($q === '' ? '?' : $q . '&') . 'u=' . $user->ID;
            },
            $html
        );
    });
});
