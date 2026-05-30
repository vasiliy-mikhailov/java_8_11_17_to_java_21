package com.example.springbootproject.model;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class Alien {

    @Autowired
    private Computer computer;

    public void compile() {
        this.computer.compile();
    }

    public Computer getComputer() {
        return computer;
    }

    public void setComputer(Computer computer) {
        this.computer = computer;
    }

    public Alien(Computer computer) {
        this.computer = computer;
    }

    public Alien() {
    }

}
