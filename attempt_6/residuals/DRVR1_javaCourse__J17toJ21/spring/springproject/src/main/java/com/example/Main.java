package com.example;

import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.support.ClassPathXmlApplicationContext;

import com.example.config.AppConfig;

public class Main {
    public static void main(String[] args) {

        // Xml based bean config
        // ApplicationContext context = new
        // ClassPathXmlApplicationContext("context.xml");

        // Java based bean config
        ApplicationContext context = new AnnotationConfigApplicationContext(AppConfig.class);
        Alien alien = (Alien) context.getBean("alien");
        alien.code();
        alien.useComputer();
    }
}
