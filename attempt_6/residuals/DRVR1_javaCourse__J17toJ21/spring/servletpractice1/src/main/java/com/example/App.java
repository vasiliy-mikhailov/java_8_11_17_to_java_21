package com.example;

import org.apache.catalina.startup.Tomcat;
import java.io.File;

import org.apache.catalina.Context;

public class App {
    public static void main(String[] args) throws Exception {
        Tomcat tomcat = new Tomcat();
        tomcat.setPort(8080);

        File base = new File(System.getProperty("java.io.tmpdir"));

        Context context = tomcat.addContext("", base.getAbsolutePath());
        Tomcat.addServlet(context, "HelloServlet", new HelloServlet());
        context.addServletMappingDecoded("/hello", "HelloServlet");
        // Iniciar
        tomcat.getConnector();
        tomcat.start();
        tomcat.getServer().await();
    }
}
