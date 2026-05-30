package com.example.springbootproject.repository;

import org.springframework.stereotype.Repository;

import com.example.springbootproject.model.LaptopComputer;

@Repository
public class LaptopRepository {
    public LaptopComputer save(LaptopComputer laptop) {
        System.out.println("Repo: Saving laptop");
        return laptop;
    }
}
