package com.example;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class Alien {
    private String name;
    private int age;

    @Autowired
    private Computer lap1;

    public void code() {
        System.out.println("Coding in hand...");
    }

    public void useComputer() {
        this.lap1.use();
    }

    public Alien() {
    }

    public Alien(String name, int age, Computer computer) {
        this.name = name;
        this.age = age;
        this.lap1 = computer;
    }

    public void setName(String name) {
        this.name = name;
    }

    public void setAge(int age) {
        this.age = age;
    }

    public void setLap1(Computer computer) {
        this.lap1 = computer;
    }

}
