package com.example;

import org.springframework.stereotype.Component;

@Component
public class Laptop implements Computer {
    public void use() {
        System.out.println("using laptop computer");
    }
}
