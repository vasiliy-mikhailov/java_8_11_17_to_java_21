package com.example.springbootproject.model;

import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

@Component
@Primary
public class LaptopComputer implements Computer {
    public void compile() {
        System.out.println("Compiling as a laptop.");
    }

}
