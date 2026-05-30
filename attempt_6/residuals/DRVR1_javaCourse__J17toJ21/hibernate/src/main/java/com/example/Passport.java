package com.example;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;

import lombok.Data;

@Entity
@NoArgsConstructor
@Data
@AllArgsConstructor
public class Passport {
    @Id
    private long id;
    private String country;
}
